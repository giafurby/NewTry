"""v3.1: Befunde der unabhängigen Prüfung (QS-Agent, 12.11.2026) – jeder Test stellt einen Befund nach.

K1  Earn-Umbuchungen (verspätete Rücknahme/Anlage) dürfen nie als Ein-/Auszahlung zählen oder den Notstopp auslösen.
K2  Eine echte Auszahlung während eines Rückgangs darf den Notstopp nicht auslösen.
M1  Binance: höchstens ein Earn-Auftrag je 3 Sekunden – zwei Crash-Käufe in derselben Kerze klappen trotzdem.
M2  Anlage mit autoSubscribe=false.  M3  Eigenes Earn-Guthaben des Nutzers bleibt seins.
M4  Ausschalten holt das Geld zurück; im Notstopp wird nichts angelegt.  M5  Vor einem Verkauf keine Earn-Abfrage.
G1  Zinszähler bleibt nach voller Rücknahme.  G2  Erster Monatsbericht zählt nur den gemessenen Zeitraum.
G8  Verkaufsgebühr in der Basiswährung zählt als Kosten.
"""
import ccxt
import pytest

from exchange import Fill
from fakes import (DIP_TF, SIGNAL_CLOSE_MS, SIGNAL_TS, Clock, FakeExchange, dip_candles, last_close, make_bot,
                   trend_candles)
from test_bot import market, scan_now, started

DIP_BAR = SIGNAL_CLOSE_MS - DIP_TF
SYMBOLS = ["ETH/USDC", "BTC/USDC", "SOL/USDC", "XRP/USDC"]


def earn_started(tmp_path, exchange, **overrides):
    overrides.setdefault("earn_enabled", True)
    overrides.setdefault("earn_reserve", 60.0)
    return started(tmp_path, exchange, **overrides)


def refresh_minute(bot, clock):
    clock.advance(61)
    bot.tick()


def flows(telegram):
    return [t for t in telegram.sent if "Einzahlung erkannt" in t or "Auszahlung erkannt" in t]


def dip_exchange(cls, usdc, drops):
    exchange = cls({"USDC": usdc}, {s: 100.0 for s in SYMBOLS})
    for i, s in enumerate(SYMBOLS):
        exchange.candles[s] = trend_candles(SIGNAL_TS, breakout=False, start=50.0 + 10 * i)
        exchange.candles_15m[s] = dip_candles(DIP_BAR, drops.get(s, 0.0))
        exchange.prices[s] = exchange.candles_15m[s][-2][4]
    return exchange


# ---------------------------------------------------------------- K1: Umbuchungen sind keine Kapitalflüsse

def test_delayed_redemption_then_buy_with_the_reserve_books_no_flow(tmp_path):
    exchange = market(signals=())
    bot, telegram, clock = earn_started(tmp_path, exchange, earn_reserve=20.0, max_position_pct=50.0,
                                        earn_redeem_wait_s=4.0)
    refresh_minute(bot, clock)
    assert exchange.earn["USDC"] == pytest.approx(130.0)
    exchange.earn_redeem_delay = 6                         # Gutschrift erst beim 6. Kontostand-Abruf
    exchange.candles["ETH/USDC"] = trend_candles(SIGNAL_TS, breakout=True, start=50.0)
    exchange.prices["ETH/USDC"] = last_close(exchange.candles["ETH/USDC"], SIGNAL_CLOSE_MS + 60_000)
    scan_now(bot, clock)
    assert telegram.any("noch nicht gutgeschrieben") and "ETH/USDC" in bot.st["positions"]
    assert bot.equity == pytest.approx(150.0, abs=0.5)     # der Betrag unterwegs zählt weiter
    for _ in range(4):
        refresh_minute(bot, clock)
    assert not flows(telegram)
    assert bot.st["net_deposits"] == pytest.approx(0.0, abs=1e-6)
    assert bot.st["earn"]["transit"] is None               # angekommen
    assert bot.st["peak_equity"] == pytest.approx(150.0, abs=0.5)


def test_delayed_redemption_without_buy_does_not_trigger_the_emergency_stop(tmp_path):
    exchange = dip_exchange(FakeExchange, 1000.0, {"ETH/USDC": 0.12})
    clock = Clock(SIGNAL_CLOSE_MS - 3_600_000)
    bot, telegram = make_bot(tmp_path, exchange, clock, dip_enabled=True, earn_enabled=True, earn_reserve=60.0,
                             earn_redeem_wait_s=4.0, max_drawdown_pct=30.0)
    bot.startup()
    refresh_minute(bot, clock)
    assert exchange.earn["USDC"] == pytest.approx(940.0)
    bot.st["peak_equity"] = 1370.0                          # echter Rückgang 27 % – unter der Grenze
    refresh_minute(bot, clock)
    exchange.earn_redeem_delay = 5
    clock.set_ms(SIGNAL_CLOSE_MS + 30_000)                  # Crash-Signal ETH −12 %
    bot.tick()
    for _ in range(3):
        refresh_minute(bot, clock)
    assert not flows(telegram)
    assert not bot.st["halted"]
    assert bot.equity == pytest.approx(1000.0, abs=0.5)


class LaggingEarnExchange(FakeExchange):
    """Binance zeigt eine Anlage erst ein paar Abfragen später in der Position."""
    lag = 0

    def sapi_post_simple_earn_flexible_subscribe(self, params):
        result = super().sapi_post_simple_earn_flexible_subscribe(params)
        self._hidden = (str(params["productId"])[:-3], float(params["amount"]), self.lag)
        return result

    def sapi_get_simple_earn_flexible_position(self, params=None):
        out = super().sapi_get_simple_earn_flexible_position(params)
        hidden = getattr(self, "_hidden", None)
        if hidden and hidden[2] > 0:
            asset, amount, left = hidden
            for row in out["rows"]:
                if row["asset"] == asset:
                    row["totalAmount"] = repr(float(row["totalAmount"]) - amount)
            self._hidden = (asset, amount, left - 1)
        return out


def test_subscription_shown_late_by_binance_books_no_flow(tmp_path):
    exchange = LaggingEarnExchange({"USDC": 150.0}, {s: 100.0 for s in SYMBOLS})
    for i, s in enumerate(SYMBOLS):
        exchange.candles[s] = trend_candles(SIGNAL_TS, breakout=False, start=50.0 + 10 * i)
        exchange.prices[s] = last_close(exchange.candles[s], SIGNAL_CLOSE_MS + 60_000)
    clock = Clock(SIGNAL_CLOSE_MS - 3_600_000)
    bot, telegram = make_bot(tmp_path, exchange, clock, earn_enabled=True, earn_reserve=60.0, max_drawdown_pct=30.0)
    bot.startup()
    bot.st["peak_equity"] = 190.0                           # echter Rückgang 21 %
    exchange.lag = 3
    for _ in range(5):
        refresh_minute(bot, clock)
    assert not flows(telegram) and not bot.st["halted"]
    assert bot.earn_amount == pytest.approx(90.0)


# ---------------------------------------------------------------- K2: Auszahlung im Rückgang

def test_withdrawal_during_a_drawdown_keeps_the_drawdown_percentage(tmp_path):
    exchange = market(signals=(), usdc=800.0)
    bot, telegram, clock = started(tmp_path, exchange, max_drawdown_pct=30.0)
    bot.st["peak_equity"] = 1000.0                          # 20 % unter dem Höchststand
    refresh_minute(bot, clock)
    exchange.balances["USDC"] -= 400.0                      # Nutzer hebt die Hälfte ab
    refresh_minute(bot, clock)
    assert telegram.any("Auszahlung erkannt: −400,00 USDC")
    assert not bot.st["halted"]
    assert bot.st["peak_equity"] == pytest.approx(500.0)    # Höchststand halbiert: weiter 20 % Rückgang
    exchange.balances["USDC"] += 100.0                      # Einzahlung danach: Höchststand + Betrag
    refresh_minute(bot, clock)
    assert bot.st["peak_equity"] == pytest.approx(600.0)


# ---------------------------------------------------------------- M1: Abstand zwischen Rücknahmen

class RateLimitedEarn(FakeExchange):
    clock = None
    last_redeem = -1e9

    def sapi_post_simple_earn_flexible_redeem(self, params):
        now = self.clock()
        if now - self.last_redeem < 3.0:
            raise ccxt.RateLimitExceeded('binance {"code":-1003,"msg":"Too many requests"}')
        self.last_redeem = now
        return super().sapi_post_simple_earn_flexible_redeem(params)


def test_two_crash_buys_in_one_candle_respect_the_redemption_rate_limit(tmp_path):
    exchange = dip_exchange(RateLimitedEarn, 1000.0, {"ETH/USDC": 0.12, "BTC/USDC": 0.12})
    clock = Clock(SIGNAL_CLOSE_MS - 3_600_000)
    exchange.clock = clock
    bot, telegram = make_bot(tmp_path, exchange, clock, dip_enabled=True, earn_enabled=True, earn_reserve=60.0)
    bot.startup()
    refresh_minute(bot, clock)
    clock.set_ms(SIGNAL_CLOSE_MS + 30_000)
    bot.tick()
    dips = [p for p in bot.st["positions"].values() if p.get("kind") == "dip"]
    assert len(dips) == 2 and not telegram.any("abgelehnt")


def test_reserve_is_at_least_a_share_of_capital(tmp_path):
    exchange = dip_exchange(FakeExchange, 1000.0, {})
    clock = Clock(SIGNAL_CLOSE_MS - 3_600_000)
    bot, telegram = make_bot(tmp_path, exchange, clock, dip_enabled=True, earn_enabled=True, earn_reserve=60.0,
                             earn_reserve_pct=30.0)
    bot.startup()
    refresh_minute(bot, clock)
    assert exchange.balances["USDC"] == pytest.approx(300.0)   # 30 % von 1.000 bleiben frei: ein Crash-Kauf ohne Rücknahme
    assert exchange.earn["USDC"] == pytest.approx(700.0)


# ---------------------------------------------------------------- M2, M3, M4

def test_subscription_switches_off_binance_auto_subscribe(tmp_path):
    exchange = market(signals=())
    bot, telegram, clock = earn_started(tmp_path, exchange)
    refresh_minute(bot, clock)
    assert exchange.last_subscribe.get("autoSubscribe") is False


def test_users_own_earn_balance_is_not_adopted(tmp_path):
    exchange = market(signals=())
    started(tmp_path, exchange)                              # Betrieb ohne Earn
    exchange.earn["USDC"] = 500.0                            # Ersparnis des Nutzers, nicht vom Bot
    clock = Clock(SIGNAL_CLOSE_MS - 3_000_000)
    bot, telegram = make_bot(tmp_path, exchange, clock, earn_enabled=True)
    bot.startup()
    for _ in range(3):
        refresh_minute(bot, clock)
    assert not flows(telegram)
    assert bot.equity == pytest.approx(150.0)
    assert exchange.earn["USDC"] == pytest.approx(590.0)     # 90 vom Bot dazu, die 500 bleiben unberührt
    bot.ensure_cash(10_000.0)                                # Kauf braucht alles: nur das Eigene zurückholen
    assert exchange.earn["USDC"] == pytest.approx(500.0)


def test_switching_earn_off_brings_the_bots_money_back(tmp_path):
    exchange = market(signals=())
    bot, telegram, clock = earn_started(tmp_path, exchange)
    refresh_minute(bot, clock)
    exchange.earn["USDC"] += 25.0                            # dazu eigenes Guthaben des Nutzers
    bot2, telegram2 = make_bot(tmp_path, exchange, clock, earn_enabled=False)
    bot2.startup()
    refresh_minute(bot2, clock)
    assert exchange.earn["USDC"] == pytest.approx(25.0)      # nur das Eigene zurück
    assert exchange.balances["USDC"] == pytest.approx(150.0)
    assert telegram2.any("Earn ist ausgeschaltet") and not flows(telegram2)
    assert bot2.earn_amount == pytest.approx(0.0)


def test_nothing_is_subscribed_while_halted(tmp_path):
    exchange = market(signals=())
    bot, telegram, clock = earn_started(tmp_path, exchange)
    bot.st["halted"], bot.st["halt_reason"] = True, "Test"
    refresh_minute(bot, clock)
    assert not exchange.earn.get("USDC")


# ---------------------------------------------------------------- M5: Verkauf ohne Earn-Abfrage

class CountingEarn(FakeExchange):
    reads = 0

    def sapi_get_simple_earn_flexible_position(self, params=None):
        self.reads += 1
        return super().sapi_get_simple_earn_flexible_position(params)


def test_stop_sale_does_not_wait_for_simple_earn(tmp_path):
    exchange = CountingEarn({"USDC": 150.0}, {s: 100.0 for s in SYMBOLS})
    for i, s in enumerate(SYMBOLS):
        exchange.candles[s] = trend_candles(SIGNAL_TS, breakout=s == "ETH/USDC", start=50.0 + 10 * i)
        exchange.prices[s] = last_close(exchange.candles[s], SIGNAL_CLOSE_MS + 60_000)
    clock = Clock(SIGNAL_CLOSE_MS - 3_600_000)
    bot, telegram = make_bot(tmp_path, exchange, clock, earn_enabled=True, earn_reserve=20.0)
    bot.startup()
    scan_now(bot, clock)
    pos = bot.st["positions"]["ETH/USDC"]
    exchange.prices["ETH/USDC"] = pos["stop"] * 0.99
    reads = exchange.reads
    clock.advance(10)                                        # nur die 10-Sekunden-Prüfung, kein Minuten-Abgleich
    bot.tick()
    assert "ETH/USDC" not in bot.st["positions"]
    assert exchange.reads == reads


# ---------------------------------------------------------------- G1: Zinsen

def test_interest_counter_survives_a_full_redemption(tmp_path):
    exchange = market(signals=())
    bot, telegram, clock = earn_started(tmp_path, exchange, earn_reserve=20.0)
    refresh_minute(bot, clock)
    exchange.accrue_earn(365.0)                              # 130 × 4 % = 5,20
    refresh_minute(bot, clock)
    assert bot.earn_rewards_since_start() == pytest.approx(5.2, abs=1e-6)
    bot.ensure_cash(10_000.0)                                # alles zurückholen
    refresh_minute(bot, clock)
    assert bot.earn_rewards_since_start() == pytest.approx(5.2, abs=1e-6)
    assert not flows(telegram)


def test_interest_on_the_users_own_part_is_not_the_bots(tmp_path):
    exchange = market(signals=())
    bot, telegram, clock = earn_started(tmp_path, exchange)
    refresh_minute(bot, clock)                               # Bot legt 90 an
    exchange.earn["USDC"] += 90.0                            # Nutzer legt selbst noch 90 dazu
    refresh_minute(bot, clock)
    exchange.accrue_earn(365.0)                              # 180 × 4 % = 7,20, davon die Hälfte für den Bot
    refresh_minute(bot, clock)
    assert bot.earn_rewards_since_start() == pytest.approx(3.6, abs=1e-6)
    assert not flows(telegram)


# ---------------------------------------------------------------- G2: Monatsbericht

def test_first_monthly_report_covers_only_the_measured_period(tmp_path):
    from datetime import datetime, timezone
    exchange = market(signals=("ETH/USDC",))
    bot, telegram, clock = started(tmp_path, exchange, report_hour=0)
    scan_now(bot, clock)                                     # Kauf …
    exchange.prices["ETH/USDC"] = bot.st["positions"]["ETH/USDC"]["target"] * 1.01
    clock.advance(10)
    bot.tick()                                               # … und Gewinn VOR dem Bezugspunkt
    bot.st["month"] = bot.st["month_start"] = None           # wie direkt nach dem Update
    clock.set_ms(int(datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc).timestamp() * 1000))
    bot.st["last_report_day"] = None
    bot.daily_report()
    clock.set_ms(int(datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc).timestamp() * 1000))
    bot.st["last_report_day"] = None
    bot.daily_report()
    report = next(t for t in telegram.sent if "Monatsbericht 2026-11" in t)
    assert "(ab 13.11. 11:00)" in report and "Trades: 0" in report and "Handelsergebnis: +0,00" in report


# ---------------------------------------------------------------- G8: Gebühr in der Basiswährung beim Verkauf

def test_sell_fee_paid_in_the_base_coin_counts_as_cost(tmp_path):
    exchange = market(signals=("ETH/USDC",))
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock)
    pos = bot.st["positions"]["ETH/USDC"]
    price = pos["entry_price"]
    fill = Fill(order_id="x", client_id="ntsx", side="sell", amount=pos["amount"], cost=pos["amount"] * price,
                price=price, fee_base=0.001, fee_quote=0.0)
    external_before = bot.st["fees_external"]
    bot.book_sell("ETH/USDC", fill, "Test")
    trade = bot.st["closed"][-1]
    assert trade["pnl"] == pytest.approx(pos["amount"] * price - 0.001 * price - pos["cost"])
    assert bot.st["fees_external"] == pytest.approx(external_before + 0.001 * price)


# ---------------------------------------------------------------- Gutfall und Ausfall (aus der Prüfung übernommen)

def test_full_cycle_has_no_false_flows_and_capital_matches_the_account(tmp_path):
    exchange = dip_exchange(FakeExchange, 1000.0, {"ETH/USDC": 0.12})
    clock = Clock(SIGNAL_CLOSE_MS - 3_600_000)
    bot, telegram = make_bot(tmp_path, exchange, clock, dip_enabled=True, earn_enabled=True, earn_reserve=60.0)
    bot.startup()
    refresh_minute(bot, clock)
    clock.set_ms(SIGNAL_CLOSE_MS + 30_000)
    bot.tick()
    pos = bot.st["positions"]["ETH/USDC"]
    for _ in range(3):
        refresh_minute(bot, clock)
    clock.set_ms(pos["deadline_ms"] + 1000)
    bot.tick()
    assert "ETH/USDC" not in bot.st["positions"]
    refresh_minute(bot, clock)
    exchange.accrue_earn(30.0)
    refresh_minute(bot, clock)
    bot2, telegram2 = make_bot(tmp_path, exchange, clock, dip_enabled=True, earn_enabled=True, earn_reserve=60.0)
    bot2.startup()
    refresh_minute(bot2, clock)
    total = exchange.balances["USDC"] + exchange.earn["USDC"]
    assert not flows(telegram) and not flows(telegram2)
    assert bot2.equity == pytest.approx(total, abs=1e-6)


class FlakyEarn(FakeExchange):
    down = False

    def sapi_get_simple_earn_flexible_position(self, params=None):
        if self.down:
            raise ccxt.ExchangeNotAvailable("Simple Earn system maintenance")
        return super().sapi_get_simple_earn_flexible_position(params)


def test_simple_earn_outage_creates_no_flows(tmp_path):
    exchange = dip_exchange(FlakyEarn, 1000.0, {"ETH/USDC": 0.12})
    clock = Clock(SIGNAL_CLOSE_MS - 3_600_000)
    bot, telegram = make_bot(tmp_path, exchange, clock, dip_enabled=True, earn_enabled=True, earn_reserve=60.0)
    bot.startup()
    exchange.down = True
    refresh_minute(bot, clock)                               # Anlage während des Ausfalls
    clock.set_ms(SIGNAL_CLOSE_MS + 30_000)
    bot.tick()                                               # Rücknahme und Kauf während des Ausfalls
    exchange.accrue_earn(10.0)
    refresh_minute(bot, clock)
    exchange.down = False
    refresh_minute(bot, clock)
    refresh_minute(bot, clock)
    assert not flows(telegram)
    assert "ETH/USDC" in bot.st["positions"]
