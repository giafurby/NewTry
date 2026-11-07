"""Crash-Kauf: Signal, Kauf, 4-Stunden-Ausstieg, Notstop, Sperre, Grenzen und Zusammenspiel mit dem Trend."""
import pytest

import strategy
from fakes import (DIP_TF, SIGNAL_CLOSE_MS, SIGNAL_TS, Clock, FakeExchange, dip_candles, last_close, make_bot,
                   trend_candles)

SYMBOLS = ["ETH/USDC", "BTC/USDC", "SOL/USDC", "XRP/USDC"]
DIP_BAR = SIGNAL_CLOSE_MS - DIP_TF            # letzte geschlossene 15m-Kerze vor dem Prüfzeitpunkt


def dip_market(drops=None, usdc=150.0, trend_signals=()):
    drops = drops or {"ETH/USDC": 0.12}
    exchange = FakeExchange({"USDC": usdc}, {s: 100.0 for s in SYMBOLS})
    now = SIGNAL_CLOSE_MS + 60_000
    for i, symbol in enumerate(SYMBOLS):
        exchange.candles[symbol] = trend_candles(SIGNAL_TS, breakout=symbol in trend_signals, start=50.0 + 10 * i)
        exchange.candles_15m[symbol] = dip_candles(DIP_BAR, drops.get(symbol, 0.0))
        exchange.prices[symbol] = exchange.candles_15m[symbol][-2][4]
        if symbol in trend_signals:
            exchange.prices[symbol] = last_close(exchange.candles[symbol], now)
    return exchange


def started(tmp_path, exchange, **overrides):
    clock = Clock(SIGNAL_CLOSE_MS - 3_600_000)
    bot, telegram = make_bot(tmp_path, exchange, clock, dip_enabled=True, **overrides)
    bot.startup()
    return bot, telegram, clock


def at_close(bot, clock, offset_ms=30_000):
    clock.set_ms(SIGNAL_CLOSE_MS + offset_ms)
    bot.tick()


def test_dip_signal_needs_drop_and_complete_window():
    rows = dip_candles(DIP_BAR, 0.12, include_open=False)
    check = strategy.evaluate_dip("ETH/USDC", rows, 10.0)
    assert check.signal and check.change_pct == pytest.approx(-12.0)
    assert not strategy.evaluate_dip("ETH/USDC", dip_candles(DIP_BAR, 0.08, include_open=False), 10.0).signal
    gap = rows[:-5] + rows[-4:]                                   # eine Kerze fehlt (Wartung)
    assert not strategy.evaluate_dip("ETH/USDC", gap, 10.0).signal


def test_crash_buy_sizes_20_percent_and_sells_after_4_hours(tmp_path):
    exchange = dip_market()
    bot, telegram, clock = started(tmp_path, exchange)
    at_close(bot, clock)
    pos = bot.st["positions"]["ETH/USDC"]
    assert pos["kind"] == "dip" and pos["target"] is None
    assert pos["cost"] == pytest.approx(150.0 * 0.20, rel=0.01)
    assert pos["stop"] == pytest.approx(pos["entry_price"] * 0.85)
    assert pos["deadline_ms"] == pytest.approx(SIGNAL_CLOSE_MS + 30_000 + 4 * 3_600_000, abs=1000)
    assert telegram.any("CRASH-KAUF ETH") and telegram.any("⚡ Einbruch ETH")
    clock.set_ms(pos["deadline_ms"] - 1000)
    bot.tick()
    assert "ETH/USDC" in bot.st["positions"]
    clock.set_ms(pos["deadline_ms"] + 1000)
    bot.tick()
    assert "ETH/USDC" not in bot.st["positions"]
    trade = bot.st["closed"][-1]
    assert trade["kind"] == "dip" and trade["reason"].startswith("Zeit-Ausstieg")
    assert not bot.st["dip_cooldown"]                             # kein Notstop -> keine Sperre


def test_stop_starts_24h_cooldown_against_falling_knives(tmp_path):
    exchange = dip_market()
    bot, telegram, clock = started(tmp_path, exchange)
    at_close(bot, clock)
    exchange.prices["ETH/USDC"] = bot.st["positions"]["ETH/USDC"]["stop"] * 0.99
    clock.advance(10)
    bot.tick()
    assert bot.st["closed"][-1]["reason"] == "Stop"
    until = bot.st["dip_cooldown"]["ETH/USDC"]
    assert until == pytest.approx(bot.now_ms() + 24 * 3_600_000, abs=60_000)
    assert telegram.any("kein neuer Crash-Kauf")
    # nächste 15m-Kerze bricht wieder ein: gesperrt
    next_bar = DIP_BAR + DIP_TF
    exchange.candles_15m["ETH/USDC"] = dip_candles(next_bar, 0.20)
    clock.set_ms(next_bar + DIP_TF + 30_000)
    bot.tick()
    assert "ETH/USDC" not in bot.st["positions"]
    assert telegram.any("Sperre nach Notstop")


def test_max_dip_positions_and_cash_limit(tmp_path):
    exchange = dip_market(drops={s: 0.15 for s in SYMBOLS})
    bot, telegram, clock = started(tmp_path, exchange, dip_max_positions=2)
    at_close(bot, clock)
    assert sum(1 for p in bot.st["positions"].values() if p["kind"] == "dip") == 2
    assert telegram.any("schon 2 Crash-Käufe offen")


def test_dip_respects_pause_and_entry_window(tmp_path):
    exchange = dip_market()
    bot, telegram, clock = started(tmp_path, exchange)
    bot.handle("/pause")
    at_close(bot, clock)
    assert not bot.st["positions"] and telegram.any("pausiert")
    bot2, telegram2, clock2 = started(tmp_path / "b", dip_market())
    at_close(bot2, clock2, offset_ms=6 * 60 * 1000)               # 6 Minuten zu spät: Chance vorbei
    assert not bot2.st["positions"]


def test_trend_and_dip_share_capital_one_position_per_coin(tmp_path):
    exchange = dip_market(drops={"ETH/USDC": 0.12, "BTC/USDC": 0.12}, trend_signals=("ETH/USDC",))
    bot, telegram, clock = started(tmp_path, exchange)
    at_close(bot, clock)
    kinds = {s: p["kind"] for s, p in bot.st["positions"].items()}
    assert kinds == {"ETH/USDC": "dip", "BTC/USDC": "dip"}       # Crash-Kauf kam zuerst, ETH nicht doppelt
    assert telegram.any("Kaufsignal ETH: schon im Bestand")      # der Trend-Kauf auf ETH wurde bewusst ausgelassen
    assert exchange.create_calls == 2
    assert bot.quote_free >= -1e-9


def test_dip_disabled_buys_nothing(tmp_path):
    exchange = dip_market()
    clock = Clock(SIGNAL_CLOSE_MS - 3_600_000)
    bot, telegram = make_bot(tmp_path, exchange, clock, dip_enabled=False)
    bot.startup()
    at_close(bot, clock)
    assert not bot.st["positions"]


def test_restart_does_not_rebuy_same_crash_candle(tmp_path):
    exchange = dip_market()
    bot, telegram, clock = started(tmp_path, exchange)
    at_close(bot, clock)
    exchange.prices["ETH/USDC"] = bot.st["positions"]["ETH/USDC"]["stop"] * 0.99
    clock.advance(10)
    bot.tick()                                                    # sofort ausgestoppt
    bot2, telegram2 = make_bot(tmp_path, exchange, clock, dip_enabled=True, dip_cooldown_hours=0.0)
    bot2.startup()
    bot2.st["last_dip_candle"] = 0
    bot2.st["dip_cooldown"] = {}                                  # nur den Schutz vor Doppelkauf prüfen
    clock.advance(10)
    bot2.tick()
    assert "ETH/USDC" not in bot2.st["positions"]                 # dieselbe Kerze wird nie zweimal gekauft
    assert telegram2.any("auf diese Kerze schon gekauft")
