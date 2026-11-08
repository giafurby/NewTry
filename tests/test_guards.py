"""Wächter aus der Forschungsrunde v2: Ausführung, Vorwärtstest, Schlüssel-Hygiene (guards.py und Einbindung in bot.py)."""
import pytest

import guards
from fakes import DIP_TF, SIGNAL_CLOSE_MS, dip_candles
from test_dip import DIP_BAR, at_close, dip_market, started


def trades(kind, pnl_pct, n, reason="Zeit-Ausstieg nach 4 h"):
    return [{"kind": kind, "pnl_pct": pnl_pct, "pnl": pnl_pct / 10, "reason": reason, "selftest": False}] * n


# ---------------------------------------------------------------- reine Logik

def test_entry_slippage_is_measured_against_signal_close():
    st = {}
    assert guards.record_entry(st, "dip", 100.0, 101.0) == pytest.approx(1.0)
    assert guards.record_entry(st, "dip", 0.0, 101.0) is None
    assert st["slippage"]["dip"] == [1.0]
    for _ in range(60):
        guards.record_entry(st, "dip", 100.0, 100.1)
    assert len(st["slippage"]["dip"]) == guards.KEEP_SLIPPAGE


def test_dip_verdict_needs_full_window_and_clear_excess():
    st = {"slippage": {"dip": [1.0, 1.0]}}
    assert guards.dip_execution_verdict(st, 0.35, 3) is None                 # zu wenige Käufe
    st["slippage"]["dip"].append(1.0)
    verdict = guards.dip_execution_verdict(st, 0.35, 3)
    assert verdict and "+1,00 %" in verdict and "0,85 Prozentpunkte" in verdict
    assert guards.dip_execution_verdict(st, 0.0, 3) is None                  # Wächter aus
    st["slippage"]["dip"] = [0.2, 0.3, 0.4]                                   # Ø 0,30 %: nur 0,15 über der Simulation
    assert guards.dip_execution_verdict(st, 0.35, 3) is None


def test_forward_test_waits_for_30_trades_and_warns_once():
    st = {"closed": trades("trend", -3.0, 29)}
    assert guards.forward_alert(st, "trend") is None
    line = guards.forward_line(guards.forward_status(st["closed"], "trend"))
    assert "Urteil ab 30 Trades" in line and "−3,00 %" in line
    st["closed"] += trades("trend", -3.0, 1)
    text = guards.forward_alert(st, "trend")
    assert text and "−3,00 %" in text and "trägt. Der Bot handelt weiter" in text
    assert guards.forward_alert(st, "trend") is None                          # nur einmal je Abrutschen
    st["closed"] += trades("trend", 5.0, 30)                                  # erholt -> Warnung wieder scharf
    assert guards.forward_alert(st, "trend") is None and st["forward_warned"]["trend"] is False


def test_forward_test_ignores_exits_that_say_nothing_about_the_rule():
    closed = trades("dip", -5.0, 40, reason="Notstopp") + trades("dip", -5.0, 5, reason="Notverkauf (Telegram)")
    closed += [{"kind": "dip", "pnl_pct": -5.0, "reason": "Funktionstest", "selftest": True}]
    assert guards.forward_status(closed, "dip") is None
    closed += trades("dip", 1.2, 3)
    status = guards.forward_status(closed, "dip")
    assert status["trades"] == 3 and status["mean_pct"] == pytest.approx(1.2) and not status["warning"]


def test_key_problems():
    assert guards.key_problems(None) == []
    assert guards.key_problems({"enableSpotAndMarginTrading": True, "enableWithdrawals": False}) == []
    problems = guards.key_problems({"enableSpotAndMarginTrading": False, "enableWithdrawals": True})
    assert len(problems) == 2 and "AUSZAHLEN" in problems[0]


# ---------------------------------------------------------------- im Bot

def test_crash_buy_records_slippage_and_status_shows_it(tmp_path):
    exchange = dip_market()
    signal_close = exchange.candles_15m["ETH/USDC"][-2][4]
    exchange.prices["ETH/USDC"] = signal_close * 1.004                       # 0,4 % teurer als der Signal-Schluss
    bot, telegram, clock = started(tmp_path, exchange)
    at_close(bot, clock)
    pos = bot.st["positions"]["ETH/USDC"]
    assert pos["signal_price"] == pytest.approx(signal_close)
    assert pos["entry_slippage_pct"] == pytest.approx(0.4, abs=0.01)
    assert bot.st["slippage"]["dip"] == [pytest.approx(0.4, abs=0.01)]
    assert telegram.any("Kaufkurs +0,40 % gegenüber dem Signal-Schluss")
    assert not bot.st["dip_suspended"]
    bot.handle("/status")
    assert telegram.any("Ausführung Crash-Kauf: Käufe im Ø +0,40 %")


def test_bad_crash_fills_suspend_only_the_crash_rule_until_resume(tmp_path):
    exchange = dip_market()
    signal_close = exchange.candles_15m["ETH/USDC"][-2][4]
    exchange.prices["ETH/USDC"] = signal_close * 1.012                       # 1,2 % schlechter
    bot, telegram, clock = started(tmp_path, exchange, slippage_window=3)
    bot.st["slippage"]["dip"] = [1.1, 1.3]                                    # zwei frühere schlechte Käufe
    at_close(bot, clock)
    assert "ETH/USDC" in bot.st["positions"]                                  # dieser Kauf läuft normal
    assert bot.st["dip_suspended"] and telegram.any("⚠️ Crash-Kauf ausgesetzt")
    # nächste Kerze: BTC bricht ein -> kein Crash-Kauf mehr
    next_bar = DIP_BAR + DIP_TF
    exchange.candles_15m["BTC/USDC"] = dip_candles(next_bar, 0.15)
    exchange.prices["BTC/USDC"] = exchange.candles_15m["BTC/USDC"][-2][4]
    clock.set_ms(SIGNAL_CLOSE_MS + DIP_TF + 30_000)
    bot.tick()
    assert "BTC/USDC" not in bot.st["positions"]
    assert telegram.any("Crash-Kauf ausgesetzt (Käufe schlechter als simuliert")
    bot.handle("/weiter")
    assert not bot.st["dip_suspended"] and bot.st["slippage"]["dip"] == []
    assert telegram.any("Crash-Kauf ist wieder an")


def test_forward_warning_is_sent_after_a_closing_trade(tmp_path):
    exchange = dip_market()
    bot, telegram, clock = started(tmp_path, exchange)
    bot.st["closed"] = trades("dip", -2.0, 29)
    at_close(bot, clock)
    pos = bot.st["positions"]["ETH/USDC"]
    clock.set_ms(pos["deadline_ms"] + 1000)
    bot.tick()
    assert "ETH/USDC" not in bot.st["positions"]
    assert telegram.any("⚠️ Vorwärtstest Crash-Kauf")


def test_daily_key_check_warns_when_withdrawals_are_allowed(tmp_path):
    exchange = dip_market()
    exchange.sapi_get_account_apirestrictions = lambda: {"enableSpotAndMarginTrading": True, "enableWithdrawals": True}
    bot, telegram, clock = started(tmp_path, exchange)
    clock.set_ms(SIGNAL_CLOSE_MS + 14 * 3_600_000)                             # nächster Morgen nach 9 Uhr
    bot.daily_report()
    assert telegram.any("☀️ Tagesbericht") and telegram.any("Schlüssel-Prüfung: Der API-Schlüssel darf AUSZAHLEN")
