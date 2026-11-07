"""Notbremse: Stop-Order direkt bei Binance – setzen, freigeben, auslösen (auch ohne Bot), Teilausführung, Neustart."""
import pytest

from fakes import (DIP_TF, SIGNAL_CLOSE_MS, SIGNAL_TS, Clock, FakeExchange, dip_candles, last_close, make_bot,
                   open_stops, trend_candles)

SYMBOLS = ["ETH/USDC", "BTC/USDC", "SOL/USDC", "XRP/USDC"]


def market(signals=("ETH/USDC",), usdc=150.0, dips=None):
    exchange = FakeExchange({"USDC": usdc}, {s: 100.0 for s in SYMBOLS})
    now = SIGNAL_CLOSE_MS + 60_000
    for i, symbol in enumerate(SYMBOLS):
        candles = trend_candles(SIGNAL_TS, breakout=symbol in signals, start=50.0 + 10 * i)
        exchange.candles[symbol] = candles
        exchange.prices[symbol] = last_close(candles, now)
        exchange.candles_15m[symbol] = dip_candles(SIGNAL_CLOSE_MS - DIP_TF, (dips or {}).get(symbol, 0.0))
        if dips and symbol in dips:
            exchange.prices[symbol] = exchange.candles_15m[symbol][-2][4]
    return exchange


def started(tmp_path, exchange, **overrides):
    clock = Clock(SIGNAL_CLOSE_MS - 3_600_000)
    overrides.setdefault("exchange_stop", True)
    bot, telegram = make_bot(tmp_path, exchange, clock, **overrides)
    bot.startup()
    return bot, telegram, clock


def bought(tmp_path, exchange=None, **overrides):
    exchange = exchange or market()
    bot, telegram, clock = started(tmp_path, exchange, **overrides)
    clock.set_ms(SIGNAL_CLOSE_MS + 60_000)
    bot.tick()
    return exchange, bot, telegram, clock


def test_buy_places_stop_order_at_binance(tmp_path):
    exchange, bot, telegram, clock = bought(tmp_path)
    pos = bot.st["positions"]["ETH/USDC"]
    stops = open_stops(exchange)
    assert len(stops) == 1
    stop = stops[0]
    assert stop["clientOrderId"].startswith("ntx") and pos["stop_order_id"] == stop["id"]
    assert stop["triggerPrice"] == pytest.approx(pos["stop"] * 0.99, abs=0.01)
    assert stop["price"] == pytest.approx(stop["triggerPrice"] * 0.97, abs=0.01)
    assert stop["amount"] == pytest.approx(pos["amount"], abs=1e-4)
    assert exchange.locked["ETH"] == pytest.approx(stop["amount"])   # Coins bei Binance gesperrt
    assert exchange.balances["ETH"] < 1e-3
    assert telegram.any("🛡 Notbremse bei Binance ab")
    assert telegram.any("Notbremse bei Binance: an")


def test_bot_stop_cancels_exchange_stop_then_sells(tmp_path):
    exchange, bot, telegram, clock = bought(tmp_path)
    pos = dict(bot.st["positions"]["ETH/USDC"])
    exchange.prices["ETH/USDC"] = pos["stop"] * 0.999                  # unter dem Bot-Stop, über dem Auslöser
    clock.advance(10)
    bot.tick()
    assert "ETH/USDC" not in bot.st["positions"]
    assert not open_stops(exchange)
    assert exchange.orders[pos["stop_order_id"]]["status"] == "canceled"
    trade = bot.st["closed"][-1]
    assert trade["reason"] == "Stop"
    assert trade["pnl"] == pytest.approx(trade["amount"] * exchange.prices["ETH/USDC"] * 0.999 - pos["cost"], rel=1e-6)
    assert not telegram.any("Einzahlung") and not telegram.any("Auszahlung")


def test_exchange_stop_sells_while_bot_is_down(tmp_path):
    exchange, bot, telegram, clock = bought(tmp_path)
    pos = dict(bot.st["positions"]["ETH/USDC"])
    usdc_before = exchange.balances["USDC"]
    # Bot und Server sind aus – der Kurs fällt unter die Notbremse
    exchange.prices["ETH/USDC"] = pos["stop"] * 0.98
    exchange.process_stops()
    assert exchange.orders[pos["stop_order_id"]]["status"] == "closed"
    sold_for = exchange.balances["USDC"] - usdc_before
    clock.advance(3600)
    bot2, telegram2 = make_bot(tmp_path, exchange, clock, exchange_stop=True)
    bot2.startup()
    assert "ETH/USDC" not in bot2.st["positions"]
    trade = bot2.st["closed"][-1]
    assert trade["reason"] == "Notbremse an der Börse"
    assert trade["proceeds"] == pytest.approx(sold_for)
    assert trade["pnl"] == pytest.approx(sold_for - pos["cost"])
    assert telegram2.any("Die Stop-Order lag direkt bei Binance und hat ausgelöst.")
    assert not telegram2.any("Einzahlung")


def test_price_gap_while_running_books_notbremse_not_deposit(tmp_path):
    exchange, bot, telegram, clock = bought(tmp_path)
    pos = dict(bot.st["positions"]["ETH/USDC"])
    exchange.prices["ETH/USDC"] = pos["stop"] * 0.985                  # Lücke unter den Auslöser
    exchange.process_stops()                                         # Binance führt aus, bevor der Bot nachsieht
    exchange.prices["ETH/USDC"] = pos["stop"] * 1.02                   # Docht: Kurs wieder über dem Bot-Stop
    clock.advance(61)
    bot.tick()
    assert "ETH/USDC" not in bot.st["positions"]
    assert bot.st["closed"][-1]["reason"] == "Notbremse an der Börse"
    assert not telegram.any("Einzahlung")
    assert bot.st["net_deposits"] == 0


def test_partial_fill_sells_rest_at_once(tmp_path):
    exchange, bot, telegram, clock = bought(tmp_path)
    pos = dict(bot.st["positions"]["ETH/USDC"])
    stop = exchange.orders[pos["stop_order_id"]]
    exchange.fill_stop(stop["id"], stop["amount"] / 2, pos["stop"] * 0.985)   # halb ausgeführt, Rest noch offen
    clock.advance(61)
    bot.tick()
    assert "ETH/USDC" not in bot.st["positions"]
    assert not open_stops(exchange)
    reasons = [t["reason"] for t in bot.st["closed"]]
    assert "Notbremse an der Börse" in reasons and "Notbremse an der Börse (Rest)" in reasons
    assert exchange.balances.get("ETH", 0.0) + exchange.locked.get("ETH", 0.0) < 1e-3
    assert not telegram.any("Einzahlung")


def test_cancelled_in_app_is_replaced(tmp_path):
    exchange, bot, telegram, clock = bought(tmp_path)
    first = bot.st["positions"]["ETH/USDC"]["stop_order_id"]
    exchange.cancel_order(first, "ETH/USDC")                         # jemand storniert sie in der Binance-App
    clock.advance(61)
    bot.tick()
    stops = open_stops(exchange)
    assert len(stops) == 1 and stops[0]["id"] != first
    assert bot.st["positions"]["ETH/USDC"]["stop_order_id"] == stops[0]["id"]


def test_timeout_when_placing_stop_is_adopted_not_doubled(tmp_path):
    exchange = market()
    exchange.timeout_after_stop = True
    exchange, bot, telegram, clock = bought(tmp_path, exchange)
    assert len(open_stops(exchange)) == 1
    assert bot.st["positions"]["ETH/USDC"]["stop_order_id"] == open_stops(exchange)[0]["id"]


def test_restart_adopts_existing_stop_instead_of_second(tmp_path):
    exchange, bot, telegram, clock = bought(tmp_path)
    bot.st["positions"]["ETH/USDC"]["stop_order_id"] = None          # Absturz direkt nach dem Setzen, vor dem Speichern
    bot.store.save()
    bot2, telegram2 = make_bot(tmp_path, exchange, clock, exchange_stop=True)
    bot2.startup()
    assert len(open_stops(exchange)) == 1
    assert bot2.st["positions"]["ETH/USDC"]["stop_order_id"] == open_stops(exchange)[0]["id"]
    assert not telegram2.any("nicht von diesem Bot stammen")          # eigene Stop-Orders sind keine fremden


def test_small_position_reports_no_exchange_stop(tmp_path):
    # Mindestgröße (5,75 USDC) mit 20 % Abstand zum Mindestpreis: der Gegenwert der Stop-Order läge unter 5 USDC
    exchange, bot, telegram, clock = bought(tmp_path, market(usdc=12.0), exchange_stop_gap_pct=20.0)
    pos = bot.st["positions"]["ETH/USDC"]
    assert pos["ex_stop_state"] == "zu klein" and not open_stops(exchange)
    assert telegram.any("Notbremse bei Binance zu klein")
    exchange.prices["ETH/USDC"] = pos["stop"] * 0.99                  # der Bot-Stop greift trotzdem
    clock.advance(10)
    bot.tick()
    assert "ETH/USDC" not in bot.st["positions"]


def test_market_without_stop_orders(tmp_path):
    exchange = market()
    exchange.markets["ETH/USDC"]["info"] = {"orderTypes": ["LIMIT", "MARKET"]}
    exchange, bot, telegram, clock = bought(tmp_path, exchange)
    assert bot.st["positions"]["ETH/USDC"]["ex_stop_state"] == "nicht möglich"
    assert telegram.any("Notbremse bei Binance nicht möglich")


def test_crash_buy_gets_stop_released_after_4_hours(tmp_path):
    exchange = market(signals=(), dips={"BTC/USDC": 0.12})
    exchange, bot, telegram, clock = bought(tmp_path, exchange, dip_enabled=True, dip_coins=("BTC",))
    pos = dict(bot.st["positions"]["BTC/USDC"])
    stop = open_stops(exchange)[0]
    assert pos["kind"] == "dip" and stop["triggerPrice"] == pytest.approx(pos["entry_price"] * 0.85 * 0.99, abs=0.01)
    clock.set_ms(pos["deadline_ms"] + 1000)
    bot.tick()
    assert "BTC/USDC" not in bot.st["positions"] and not open_stops(exchange)
    assert bot.st["closed"][-1]["reason"].startswith("Zeit-Ausstieg")


def test_notbremse_on_crash_buy_starts_cooldown(tmp_path):
    exchange = market(signals=(), dips={"BTC/USDC": 0.12})
    exchange, bot, telegram, clock = bought(tmp_path, exchange, dip_enabled=True, dip_coins=("BTC",))
    pos = dict(bot.st["positions"]["BTC/USDC"])
    exchange.prices["BTC/USDC"] = pos["stop"] * 0.985
    exchange.process_stops()
    exchange.prices["BTC/USDC"] = pos["stop"] * 1.05
    clock.advance(61)
    bot.tick()
    assert bot.st["closed"][-1]["reason"] == "Notbremse an der Börse"
    assert bot.st["dip_cooldown"]["BTC/USDC"] > bot.now_ms()


def test_selftest_places_no_exchange_stop(tmp_path):
    exchange = market(signals=())
    bot, telegram, clock = started(tmp_path, exchange, selftest_trade=True)
    assert bot.st["selftest_done"] and exchange.create_calls == 2 and not open_stops(exchange)


def test_notstopp_releases_all_stops(tmp_path):
    exchange, bot, telegram, clock = bought(tmp_path, market(signals=("ETH/USDC", "BTC/USDC")))
    assert len(open_stops(exchange)) == 2
    bot.st["peak_equity"] = 400.0
    clock.advance(61)
    bot.tick()
    assert bot.st["halted"] and not bot.st["positions"] and not open_stops(exchange)


def test_disabled_places_nothing(tmp_path):
    exchange, bot, telegram, clock = bought(tmp_path, exchange_stop=False)
    assert "ETH/USDC" in bot.st["positions"] and not open_stops(exchange)
