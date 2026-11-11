import pytest

import strategy
from fakes import (SIGNAL_CLOSE_MS, SIGNAL_TS, TF, Clock, FakeExchange, last_close, make_bot, trend_candles)

SYMBOLS = ["ETH/USDC", "BTC/USDC", "SOL/USDC", "XRP/USDC"]


def market(signals=("ETH/USDC",), usdc=150.0, step=0.0001):
    """Börse mit Kerzen für alle Coins; `signals` brechen auf der letzten geschlossenen Kerze aus."""
    exchange = FakeExchange({"USDC": usdc}, {s: 100.0 for s in SYMBOLS}, step=step)
    now = SIGNAL_CLOSE_MS + 60_000
    for i, symbol in enumerate(SYMBOLS):
        candles = trend_candles(SIGNAL_TS, breakout=symbol in signals, start=50.0 + 10 * i)
        exchange.candles[symbol] = candles
        exchange.prices[symbol] = last_close(candles, now)
    return exchange


def started(tmp_path, exchange, clock_ms=SIGNAL_CLOSE_MS - 3_600_000, **overrides):
    clock = Clock(clock_ms)
    bot, telegram = make_bot(tmp_path, exchange, clock, **overrides)
    bot.startup()
    return bot, telegram, clock


def scan_now(bot, clock, offset_ms=60_000):
    clock.set_ms(SIGNAL_CLOSE_MS + offset_ms)
    bot.tick()


# ---------------------------------------------------------------------------------------------- Kaufen


def test_buys_on_signal_with_risk_based_size(tmp_path):
    exchange = market()
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock)
    pos = bot.st["positions"]["ETH/USDC"]
    check = strategy.evaluate("ETH/USDC", strategy.closed_candles(exchange.candles["ETH/USDC"], bot.now_ms()))
    expected_cost = min(150.0 * 0.01 / check.stop_fraction, 150.0 * 0.33)
    assert pos["cost"] == pytest.approx(expected_cost, rel=0.01)
    assert pos["stop"] == pytest.approx(pos["entry_price"] * (1 - check.stop_fraction))
    assert pos["target"] == pytest.approx(pos["entry_price"] * (1 + check.target_fraction))
    assert pos["deadline_ms"] == SIGNAL_CLOSE_MS + 120 * TF
    assert pos["amount"] == pytest.approx(exchange.balances["ETH"])       # netto nach Gebühr, wie auf dem Konto
    assert telegram.any("🟢 KAUF ETH")
    assert bot.st["entered"]["ETH/USDC"] == SIGNAL_TS
    assert bot.st["last_signal_candle"] == SIGNAL_TS
    assert telegram.any("4h-Prüfung")


def test_only_one_entry_per_signal_candle(tmp_path):
    exchange = market()
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock)
    stop = bot.st["positions"]["ETH/USDC"]["stop"]
    exchange.prices["ETH/USDC"] = stop * 0.99                # sofort ausgestoppt
    clock.advance(10)
    bot.tick()
    assert "ETH/USDC" not in bot.st["positions"]
    bot.st["last_signal_candle"] = 0                         # erzwingt erneute Prüfung derselben Kerze
    bot.scan_state = (0, set(), [])
    exchange.prices["ETH/USDC"] = stop * 1.05
    clock.advance(10)
    bot.tick()
    assert "ETH/USDC" not in bot.st["positions"]
    assert exchange.create_calls == 2                        # ein Kauf, ein Verkauf – kein zweiter Kauf


def test_max_positions_respected(tmp_path):
    exchange = market(signals=tuple(SYMBOLS))
    bot, telegram, clock = started(tmp_path, exchange, max_positions=3)
    scan_now(bot, clock)
    assert len(bot.st["positions"]) == 3
    assert "XRP/USDC" not in bot.st["positions"]
    assert telegram.any("schon 3 Trend-Positionen")


def test_pause_blocks_entries_and_resume(tmp_path):
    exchange = market()
    bot, telegram, clock = started(tmp_path, exchange)
    bot.handle("/pause")
    scan_now(bot, clock)
    assert not bot.st["positions"]
    assert telegram.any("pausiert")
    bot.handle("/weiter")
    assert not bot.st["paused"]


def test_missed_entry_window_skips_candle(tmp_path):
    exchange = market()
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock, offset_ms=strategy.ENTRY_WINDOW_MS + 60_000)
    assert not bot.st["positions"]
    assert bot.st["last_signal_candle"] == SIGNAL_TS


def test_small_account_uses_binance_minimum(tmp_path):
    exchange = market(usdc=12.0)                             # 1 % Risiko ergäbe nur ~4 USDC – unter dem Minimum
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock)
    pos = bot.st["positions"]["ETH/USDC"]
    assert 5.75 <= pos["cost"] <= 5.9                        # 5 USDC Minimum + 15 % Puffer
    assert pos["risk"] <= 12.0 * 0.03


def test_too_little_cash_is_reported_not_crashed(tmp_path):
    exchange = market(usdc=4.0)
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock)
    assert not bot.st["positions"]
    assert telegram.any("zu wenig USDC frei")
    assert exchange.create_calls == 0


def test_scan_without_signal_reports_silently(tmp_path):
    exchange = market(signals=())
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock)
    report = [t for t in telegram.sent if "4h-Prüfung" in t][-1]
    assert "Kein Kaufsignal" in report and "Am nächsten dran" in report
    assert telegram.silent[telegram.sent.index(report)] is True


# ---------------------------------------------------------------------------------------------- Verkaufen


def test_stop_loss_sells_and_books_loss_with_fees(tmp_path):
    exchange = market()
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock)
    pos = dict(bot.st["positions"]["ETH/USDC"])
    exit_price = pos["stop"] * 0.999
    exchange.prices["ETH/USDC"] = exit_price
    clock.advance(10)
    bot.tick()
    assert "ETH/USDC" not in bot.st["positions"]
    trade = bot.st["closed"][-1]
    assert trade["reason"] == "Stop"
    sold = trade["amount"]
    expected = sold * exit_price * (1 - 0.001) - pos["cost"]
    assert trade["pnl"] == pytest.approx(expected, rel=1e-6)
    assert trade["pnl"] < 0
    assert trade["r"] == pytest.approx(trade["pnl"] / pos["risk"], rel=1e-3)
    assert telegram.any("VERKAUF ETH (Trend) – Stop")
    assert not telegram.any("Einzahlung") and not telegram.any("Auszahlung")


def test_target_sells_with_profit(tmp_path):
    exchange = market()
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock)
    exchange.prices["ETH/USDC"] = bot.st["positions"]["ETH/USDC"]["target"] * 1.001
    clock.advance(10)
    bot.tick()
    trade = bot.st["closed"][-1]
    assert trade["reason"] == "Ziel" and trade["pnl"] > 0
    assert telegram.any("✅ VERKAUF ETH (Trend) – Ziel")


def test_time_stop_after_20_days(tmp_path):
    exchange = market()
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock)
    clock.set_ms(bot.st["positions"]["ETH/USDC"]["deadline_ms"] + 1000)
    bot.tick()
    assert bot.st["closed"][-1]["reason"].startswith("Zeit-Stop")


def test_drawdown_emergency_stop_sells_everything_and_halts(tmp_path):
    exchange = market(signals=("ETH/USDC", "BTC/USDC"))
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock)
    assert len(bot.st["positions"]) == 2
    bot.st["peak_equity"] = 300.0                            # Kapital ist dann 50 % unter dem Höchststand
    clock.advance(61)
    bot.tick()
    assert bot.st["halted"]
    assert not bot.st["positions"]
    assert telegram.any("NOTSTOPP")
    clock.advance(4 * 3600)                                  # auch spätere Signale werden nicht gekauft
    bot.tick()
    assert not bot.st["positions"]
    clock.advance(24 * 3600)                                 # Wartezeit nach dem Notstopp (HALT_WAIT_HOURS)
    bot.handle("/weiter")
    assert not bot.st["halted"] and bot.st["peak_equity"] == pytest.approx(bot.equity)


def test_daily_loss_limit_stops_new_buys(tmp_path):
    exchange = market()
    bot, telegram, clock = started(tmp_path, exchange)
    bot.st["day_start_equity"] = 200.0
    bot.st["day"] = bot.local(SIGNAL_CLOSE_MS).date().isoformat()
    scan_now(bot, clock)
    assert bot.st["day_limit_hit"]
    assert not bot.st["positions"]
    assert telegram.any("Tageslimit erreicht")


def test_sell_all_needs_confirmation(tmp_path):
    exchange = market(signals=("ETH/USDC", "BTC/USDC"))
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock)
    bot.handle("/notverkauf_ja")
    assert len(bot.st["positions"]) == 2                     # ohne vorheriges /notverkauf passiert nichts
    bot.handle("/notverkauf")
    bot.handle("/notverkauf_ja")
    assert not bot.st["positions"] and bot.st["paused"]


# ---------------------------------------------------------------------------------------------- Sicherheit


def test_timeout_after_fill_does_not_buy_twice(tmp_path):
    exchange = market()
    bot, telegram, clock = started(tmp_path, exchange)
    exchange.timeout_after_fill = True
    scan_now(bot, clock)
    assert exchange.create_calls == 1
    assert len(exchange.orders) == 1
    assert "ETH/USDC" in bot.st["positions"]
    assert bot.st["pending"] is None


def test_timeout_before_fill_buys_nothing_and_clears_pending(tmp_path):
    exchange = market()
    bot, telegram, clock = started(tmp_path, exchange)
    exchange.timeout_before_fill = True
    scan_now(bot, clock)
    assert not exchange.orders and not bot.st["positions"]
    assert bot.st["pending"] is None
    assert telegram.any("Kauf ETH fehlgeschlagen")


def test_crash_between_order_and_booking_is_recovered(tmp_path):
    exchange = market()
    bot, telegram, clock = started(tmp_path, exchange)
    order = exchange.create_order("ETH/USDC", "market", "buy", 0.2, None, {"newClientOrderId": "ntbcrash1"})
    bot.st["pending"] = {"client_id": "ntbcrash1", "symbol": "ETH/USDC", "side": "buy", "stop_fraction": 0.05,
                         "target_fraction": 0.4, "candle_ts": SIGNAL_TS, "atr": 1.0, "base_before": 0.0}
    bot.store.save()
    bot2, telegram2 = make_bot(tmp_path, exchange, clock)    # Neustart nach dem Absturz
    bot2.startup()
    pos = bot2.st["positions"]["ETH/USDC"]
    assert pos["amount"] == pytest.approx(0.2 * 0.999)
    assert pos["entry_price"] == pytest.approx(order["average"])
    assert bot2.st["pending"] is None
    assert telegram2.any("KAUF ETH")


def test_unknown_pending_order_is_cleared(tmp_path):
    exchange = market()
    bot, telegram, clock = started(tmp_path, exchange)
    bot.st["pending"] = {"client_id": "ntbnever", "symbol": "ETH/USDC", "side": "buy", "stop_fraction": 0.05,
                         "target_fraction": 0.4, "candle_ts": SIGNAL_TS, "atr": 1.0, "base_before": 0.0}
    bot.tick()
    assert bot.st["pending"] is None and not bot.st["positions"]


def test_deposit_is_not_profit(tmp_path):
    exchange = market(signals=())
    bot, telegram, clock = started(tmp_path, exchange)
    peak = bot.st["peak_equity"]
    exchange.balances["USDC"] += 100.0
    clock.advance(61)
    bot.tick()
    assert bot.st["net_deposits"] == pytest.approx(100.0)
    assert bot.st["peak_equity"] == pytest.approx(peak + 100.0)
    assert telegram.any("Einzahlung erkannt")
    assert "seit Start +0,00 USDC" in "\n".join(bot.summary_lines())


def test_position_sold_by_hand_is_booked_out(tmp_path):
    exchange = market()
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock)
    exchange.balances["USDC"] += exchange.balances.pop("ETH") * exchange.prices["ETH/USDC"]
    for _ in range(2):
        clock.advance(61)
        bot.tick()
    assert "ETH/USDC" not in bot.st["positions"]
    assert telegram.any("nicht mehr auf dem Konto")


def test_selftest_trade_on_first_live_start(tmp_path):
    exchange = market(signals=())
    bot, telegram, clock = started(tmp_path, exchange, selftest_trade=True)
    assert bot.st["selftest_done"]
    assert exchange.create_calls == 2
    assert not bot.st["positions"]
    assert telegram.any("Funktionstest bestanden")
    assert 149.8 < exchange.balances["USDC"] < 150.0         # nur Gebühren
    trade = bot.st["closed"][-1]
    assert trade["selftest"] and trade["reason"] == "Funktionstest"
    bot2, telegram2 = make_bot(tmp_path, exchange, clock, selftest_trade=True)
    bot2.startup()
    assert exchange.create_calls == 2                        # nur einmal


def test_paper_mode_has_no_selftest(tmp_path):
    exchange = market(signals=())
    bot, telegram, clock = started(tmp_path, exchange, mode="paper", selftest_trade=True)
    assert exchange.create_calls == 0
    assert telegram.any("📄 PAPIER")


def test_state_survives_restart(tmp_path):
    exchange = market()
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock)
    bot2, _ = make_bot(tmp_path, exchange, clock)
    bot2.startup()
    assert bot2.st["positions"]["ETH/USDC"]["amount"] == pytest.approx(bot.st["positions"]["ETH/USDC"]["amount"])


def test_commands(tmp_path):
    exchange = market()
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock)
    bot.handle("/status")
    assert "Kapital" in telegram.last() and "ETH" in telegram.last()
    bot.handle("/markt")
    assert "Marktlage" in telegram.last()
    bot.handle("/trades")
    assert "Noch keine" in telegram.last()
    bot.handle("/quatsch")
    assert "Unbekannter Befehl" in telegram.last()
    bot.handle("/hilfe")
    assert "/notverkauf" in telegram.last()


def test_daily_report_once_per_day(tmp_path):
    exchange = market(signals=())
    bot, telegram, clock = started(tmp_path, exchange)
    clock.set_ms(SIGNAL_CLOSE_MS + 12 * 3600 * 1000)        # nächster Tag 09:00 deutscher Zeit
    bot.tick()
    bot.tick()
    assert sum("Tagesbericht" in t for t in telegram.sent) == 1


def test_leftover_from_fee_is_sold_with_next_trade(tmp_path):
    exchange = market(step=0.001)
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock)
    exchange.prices["ETH/USDC"] = bot.st["positions"]["ETH/USDC"]["stop"] * 0.99
    clock.advance(10)
    bot.tick()
    dust = bot.st["dust"]["ETH/USDC"]
    assert 0 < dust < 0.001 and exchange.balances["ETH"] == pytest.approx(dust)
    for _ in range(3):                                       # weitere Trades im selben Coin
        bot.execute_buy("ETH/USDC", 0.3, {"stop_fraction": 0.05, "target_fraction": 0.5,
                                          "candle_ts": SIGNAL_TS + TF, "atr": 1.0})
        assert bot.close_position("ETH/USDC", "Test")
    assert exchange.balances["ETH"] < 0.001                  # Rest bleibt immer unter einer Schrittweite
    assert bot.st["dust"]["ETH/USDC"] == pytest.approx(exchange.balances["ETH"])


def test_hand_sale_keeps_profit_math_right(tmp_path):
    exchange = market()
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock)
    bot.refresh()
    profit_before = bot.equity - bot.st["start_equity"] - bot.st["net_deposits"]
    exchange.balances["USDC"] += exchange.balances.pop("ETH") * exchange.prices["ETH/USDC"]   # von Hand verkauft
    for _ in range(3):
        clock.advance(61)
        bot.tick()
    assert "ETH/USDC" not in bot.st["positions"]
    profit_after = bot.equity - bot.st["start_equity"] - bot.st["net_deposits"]
    assert profit_after == pytest.approx(profit_before, abs=0.01)
    assert bot.st["net_deposits"] == pytest.approx(0.0, abs=0.01)


def test_unsellable_rest_is_reported_and_kept_as_leftover(tmp_path):
    exchange = market()
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock)
    pos = bot.st["positions"]["ETH/USDC"]
    bot.st["positions"]["ETH/USDC"]["stop"] = 0.0              # Stop greift nicht, nur der Notverkauf
    exchange.prices["ETH/USDC"] = 4.0 / pos["amount"]         # Position nur noch 4 USDC wert (< 5 USDC Minimum)
    bot.handle("/notverkauf")
    bot.handle("/notverkauf_ja")
    assert "ETH/USDC" not in bot.st["positions"]
    assert bot.st["dust"]["ETH/USDC"] == pytest.approx(pos["amount"])
    assert bot.st["closed"][-1]["proceeds"] == 0.0
    assert telegram.any("nicht verkaufbar")


def test_selftest_failure_does_not_block_start_and_never_doubles(tmp_path):
    exchange = market(signals=())
    clock = Clock(SIGNAL_CLOSE_MS - 3_600_000)
    bot, telegram = make_bot(tmp_path, exchange, clock, selftest_trade=True)
    original = bot.close_position
    bot.close_position = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Netz weg"))
    bot.startup()                                            # Kauf klappt, Verkauf wirft – Start läuft trotzdem durch
    assert telegram.any("Funktionstest fehlgeschlagen")
    assert any(p.get("selftest") for p in bot.st["positions"].values())
    bot2, telegram2 = make_bot(tmp_path, exchange, clock, selftest_trade=True)
    bot2.startup()                                           # Neustart: kein zweiter Testkauf
    assert exchange.create_calls == 1
    clock.advance(10)
    bot2.tick()                                              # offener Test wird verkauft und abgehakt
    assert not bot2.st["positions"] and bot2.st["selftest_done"]
    assert telegram2.any("Funktionstest bestanden")
    del original
