"""v3: Zinsen auf ungenutztes Guthaben (Simple Earn), Einzahlungen sofort nutzen, Monatsbericht, Wartezeit nach
Notstopp, /warum und /erwartung."""
import pytest

from fakes import SIGNAL_CLOSE_MS, SIGNAL_TS, last_close, trend_candles
from test_bot import market, scan_now, started


def earn_started(tmp_path, exchange, **overrides):
    overrides.setdefault("earn_enabled", True)
    overrides.setdefault("earn_reserve", 60.0)
    return started(tmp_path, exchange, **overrides)


def refresh_minute(bot, clock):
    clock.advance(61)
    bot.tick()


# ---------------------------------------------------------------- Anlegen und Kapital

def test_idle_cash_above_reserve_is_subscribed_and_still_counts_as_capital(tmp_path):
    exchange = market(signals=())
    bot, telegram, clock = earn_started(tmp_path, exchange)
    refresh_minute(bot, clock)
    assert exchange.earn["USDC"] == pytest.approx(90.0)                      # 150 − 60 Reserve
    assert exchange.balances["USDC"] == pytest.approx(60.0)
    assert bot.equity == pytest.approx(150.0)                                 # angelegt zählt mit
    assert bot.st["net_deposits"] == 0.0 and not telegram.any("Auszahlung")  # Anlage ist keine Auszahlung
    assert telegram.any("in Simple Earn angelegt")
    refresh_minute(bot, clock)
    assert exchange.earn["USDC"] == pytest.approx(90.0)                      # nichts doppelt angelegt
    text = "\n".join(bot.summary_lines())
    assert "angelegt 90,00 USDC" in text and "4,0 % p. a." in text


def test_earn_is_off_by_default_and_in_paper_mode(tmp_path):
    exchange = market(signals=())
    bot, telegram, clock = started(tmp_path, exchange)
    refresh_minute(bot, clock)
    assert not exchange.earn
    bot, telegram, clock = earn_started(tmp_path / "p", market(signals=()), mode="paper")
    refresh_minute(bot, clock)
    assert not exchange.earn


def test_interest_is_shown_and_not_counted_as_deposit(tmp_path):
    exchange = market(signals=())
    bot, telegram, clock = earn_started(tmp_path, exchange)
    refresh_minute(bot, clock)
    exchange.accrue_earn(365.0)                                              # ein Jahr Zinsen auf 90 USDC zu 4 %
    refresh_minute(bot, clock)
    assert bot.earn_rewards_since_start() == pytest.approx(3.6, abs=0.01)
    assert bot.equity == pytest.approx(153.6, abs=0.01)
    assert bot.st["net_deposits"] == 0.0                                     # Zinsen sind kein Kapitalfluss
    assert "Zinsen +3,6000 USDC" in "\n".join(bot.summary_lines())


# ---------------------------------------------------------------- Rücknahme vor dem Kauf

def test_buy_redeems_from_earn_when_free_cash_is_short(tmp_path):
    exchange = market(signals=())
    bot, telegram, clock = earn_started(tmp_path, exchange, earn_reserve=20.0, max_position_pct=50.0)
    refresh_minute(bot, clock)
    assert exchange.balances["USDC"] == pytest.approx(20.0) and exchange.earn["USDC"] == pytest.approx(130.0)
    # jetzt ein Trend-Signal mit einer Position deutlich über der Reserve
    exchange.candles["ETH/USDC"] = trend_candles(SIGNAL_TS, breakout=True, start=50.0)
    exchange.prices["ETH/USDC"] = last_close(exchange.candles["ETH/USDC"], SIGNAL_CLOSE_MS + 60_000)
    scan_now(bot, clock)
    pos = bot.st["positions"]["ETH/USDC"]
    assert pos["cost"] > 20.0                                                # mehr als die Reserve: Geld kam aus Earn
    assert bot.equity == pytest.approx(150.0, rel=0.01)
    assert not telegram.any("Einzahlung") and not telegram.any("Auszahlung")
    assert "zurückgeholt" in bot.st["earn"]["last_action"]


def test_delayed_redemption_buys_with_the_reserve_and_warns(tmp_path):
    exchange = market(signals=())
    bot, telegram, clock = earn_started(tmp_path, exchange, earn_reserve=20.0, max_position_pct=50.0,
                                        earn_redeem_wait_s=4.0)
    refresh_minute(bot, clock)
    exchange.earn_redeem_delay = 50                                          # Gutschrift kommt (fast) nie
    bot.sleep = lambda s: clock.advance(s)
    exchange.candles["ETH/USDC"] = trend_candles(SIGNAL_TS, breakout=True, start=50.0)
    exchange.prices["ETH/USDC"] = last_close(exchange.candles["ETH/USDC"], SIGNAL_CLOSE_MS + 60_000)
    scan_now(bot, clock)
    assert telegram.any("noch nicht gutgeschrieben")
    pos = bot.st["positions"].get("ETH/USDC")
    assert pos is not None and pos["cost"] <= 20.0                           # gekauft mit der Reserve


def test_rejected_redemption_does_not_block_the_buy(tmp_path):
    exchange = market(signals=())
    bot, telegram, clock = earn_started(tmp_path, exchange, earn_reserve=20.0, max_position_pct=50.0)
    refresh_minute(bot, clock)
    exchange.earn_reject_redeem = True
    exchange.candles["ETH/USDC"] = trend_candles(SIGNAL_TS, breakout=True, start=50.0)
    exchange.prices["ETH/USDC"] = last_close(exchange.candles["ETH/USDC"], SIGNAL_CLOSE_MS + 60_000)
    scan_now(bot, clock)
    assert telegram.any("Rücknahme") and telegram.any("abgelehnt")
    assert "ETH/USDC" in bot.st["positions"]
    assert bot.st["earn"]["amount"] == pytest.approx(130.0)                  # Buchung unverändert


# ---------------------------------------------------------------- Einzahlung

def test_deposit_is_used_at_the_next_check_and_announced(tmp_path):
    exchange = market(signals=())
    bot, telegram, clock = started(tmp_path, exchange)
    exchange.balances["USDC"] += 100.0
    refresh_minute(bot, clock)
    assert bot.equity == pytest.approx(250.0)
    assert telegram.any("Einzahlung erkannt: +100,00 USDC") and telegram.any("die nächste Prüfung rechnet damit")
    exchange.candles["ETH/USDC"] = trend_candles(SIGNAL_TS, breakout=True, start=50.0)
    exchange.prices["ETH/USDC"] = last_close(exchange.candles["ETH/USDC"], SIGNAL_CLOSE_MS + 60_000)
    scan_now(bot, clock)
    pos = bot.st["positions"]["ETH/USDC"]
    assert pos["risk"] > 1.5 * 1.3                                           # deutlich mehr als 1 % von 150
    assert pos["risk"] == pytest.approx(0.01 * 250.0, rel=0.1)              # 1 % von 250 (Rundung auf Schrittweite)


# ---------------------------------------------------------------- Notstopp mit Wartezeit

def test_resume_after_emergency_stop_requires_the_waiting_time(tmp_path):
    exchange = market(signals=("ETH/USDC",))
    bot, telegram, clock = started(tmp_path, exchange, max_drawdown_pct=25.0, halt_wait_hours=24.0)
    scan_now(bot, clock)
    bot.st["peak_equity"] = 300.0                                             # Kapital liegt 50 % darunter
    refresh_minute(bot, clock)
    assert bot.st["halted"] and telegram.any("frühestens in 24 Stunden")
    bot.handle("/weiter")
    assert bot.st["halted"] and telegram.any("geht /weiter erst ab")
    clock.advance(24 * 3600 + 1)
    bot.handle("/weiter")
    assert not bot.st["halted"]


# ---------------------------------------------------------------- Monatsbericht

def test_monthly_report_separates_deposits_trading_fees_and_interest(tmp_path):
    from datetime import datetime, timezone
    exchange = market(signals=("ETH/USDC",))
    bot, telegram, clock = earn_started(tmp_path, exchange, report_hour=0)
    clock.set_ms(int(datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc).timestamp() * 1000))
    bot.daily_report()                                       # erster Lauf: Bezugspunkt für den Monat
    assert bot.st["month"] == "2026-11"
    exchange.balances["USDC"] += 100.0                       # Einzahlung im November
    refresh_minute(bot, clock)
    exchange.accrue_earn(30.0)
    refresh_minute(bot, clock)
    clock.set_ms(int(datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc).timestamp() * 1000))
    bot.st["last_report_day"] = None
    bot.daily_report()
    report = next(t for t in telegram.sent if "Monatsbericht 2026-11" in t)
    assert "Einzahlungen: +100,00 USDC" in report
    assert "Zinsen (Earn): +0," in report
    assert "Handelsergebnis:" in report and "Trades: 0" in report
    assert bot.st["month"] == "2026-12"


# ---------------------------------------------------------------- /warum und /erwartung

def test_why_lists_decisions_of_the_day(tmp_path):
    exchange = market(signals=("ETH/USDC",))
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock)
    bot.handle("/warum")
    text = telegram.last()
    assert "Trend ETH: Ausbruch" in text and "gekauft" in text and "Plätze: Trend 1/3" in text


def test_why_explains_silence(tmp_path):
    bot, telegram, clock = started(tmp_path, market(signals=()))
    bot.handle("/warum")
    assert "Keine Signale" in telegram.last()


def test_expectation_scales_with_capital(tmp_path):
    bot, telegram, clock = started(tmp_path, market(signals=()))
    bot.handle("/erwartung")
    text = telegram.last()
    assert "Kapital 150,00 USDC" in text and "keine Prognose" in text
    assert "+2,9 % ≈ +4,35 USDC" in text                     # Median 2,9 % von 150
    assert "Seit 2025" in text


# ---------------------------------------------------------------- Startklar-Check

def test_check_reports_earn_when_enabled(tmp_path, capsys):
    from bot import run_check
    from exchange import Broker
    from fakes import FakeTelegram, make_settings
    exchange = market(signals=())
    exchange.earn["USDC"] = 90.0
    settings = make_settings(tmp_path, earn_enabled=True)
    assert run_check(settings, Broker(exchange, "USDC", sleep=lambda _s: None), FakeTelegram()) == 0
    out = capsys.readouterr().out
    assert "Simple Earn erreichbar: 90,00 USDC angelegt" in out and "Reserve im Spot-Konto: 60,00 USDC" in out


def test_check_fails_when_earn_enabled_but_key_lacks_the_right(tmp_path, capsys):
    import ccxt
    from bot import run_check
    from exchange import Broker
    from fakes import FakeTelegram, make_settings
    exchange = market(signals=())

    def denied(params=None):
        raise ccxt.PermissionDenied("binance Simple Earn permission missing")
    exchange.sapi_get_simple_earn_flexible_position = denied
    settings = make_settings(tmp_path, earn_enabled=True)
    assert run_check(settings, Broker(exchange, "USDC", sleep=lambda _s: None), FakeTelegram()) == 1
    assert "Simple Earn ist nicht abfragbar" in capsys.readouterr().out
