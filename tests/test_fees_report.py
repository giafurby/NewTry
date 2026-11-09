"""Gebühren in einer dritten Währung (BNB-Rabatt) und der 4h-Bericht nach einem Kauf."""
import pytest

from exchange import Broker
from fakes import SIGNAL_TS, FakeExchange, last_close, trend_candles
from test_bot import SYMBOLS, market, scan_now, started

BNB_PRICE = 700.0


class BnbFeeExchange(FakeExchange):
    """Wie Binance mit BNB-Rabatt: Die Gebühr wird nicht vom Coin oder von USDC abgezogen, sondern vom BNB-Guthaben."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prices["BNB/USDC"] = BNB_PRICE
        self.balances["BNB"] = 1.0

    def create_order(self, symbol, type, side, amount, price=None, params=None):
        order = super().create_order(symbol, type, side, amount, price, params)
        if type.upper() == "STOP_LOSS_LIMIT":
            return order
        paid = order["fee"]["cost"]
        currency = order["fee"]["currency"]
        value = paid * (order["average"] if currency != "USDC" else 1.0)        # Wert der bisherigen Gebühr in USDC
        self.balances[currency] += paid                                          # nicht vom Coin / von USDC abziehen
        bnb = value / BNB_PRICE
        self.balances["BNB"] -= bnb
        entry = {"cost": bnb, "currency": "BNB"}
        order["fee"], order["fees"] = entry, [dict(entry)]
        self.orders[order["id"]].update(fee=entry, fees=[dict(entry)])
        return dict(order)


def bnb_market(signals=("ETH/USDC",)):
    base = market(signals=signals)
    exchange = BnbFeeExchange({"USDC": 150.0}, {s: base.prices[s] for s in SYMBOLS})
    exchange.candles = base.candles
    exchange.candles_15m = base.candles_15m
    return exchange


# ---------------------------------------------------------------- Umrechnung im Broker

def order_with_fee(cost, fee_cost, currency):
    return {"id": "1", "filled": 1.0, "cost": cost, "average": cost, "status": "closed",
            "fees": [{"cost": fee_cost, "currency": currency}]}


def test_bnb_fee_is_converted_to_usdc_with_the_bnb_price():
    exchange = FakeExchange({"USDC": 100.0}, {"ETH/USDC": 100.0, "BNB/USDC": BNB_PRICE})
    broker = Broker(exchange, "USDC", sleep=lambda _s: None)
    broker.load_markets(["ETH"])
    fill = broker.fill_from_order(order_with_fee(100.0, 2.797e-05 * 1000, "BNB"), "ETH/USDC", "buy", "x")
    assert fill.fee_other == pytest.approx(0.02797 * BNB_PRICE)
    assert fill.fee_value == pytest.approx(fill.fee_other)
    assert fill.fee_base == 0.0 and fill.fee_quote == 0.0
    assert "e-" not in fill.fee_note and "BNB" in fill.fee_note and "≈" in fill.fee_note and "USDC" in fill.fee_note
    assert "geschätzt" not in fill.fee_note


def test_bnb_fee_falls_back_to_the_discount_rate_without_a_bnb_price():
    exchange = FakeExchange({"USDC": 100.0}, {"ETH/USDC": 100.0})                  # kein BNB/USDC-Kurs
    broker = Broker(exchange, "USDC", sleep=lambda _s: None)
    broker.load_markets(["ETH"])
    fill = broker.fill_from_order(order_with_fee(100.0, 0.0001, "BNB"), "ETH/USDC", "buy", "x")
    assert fill.fee_other == pytest.approx(100.0 * 0.00075) and "geschätzt" in fill.fee_note


def test_fee_in_base_or_quote_is_unchanged():
    exchange = FakeExchange({"USDC": 100.0}, {"ETH/USDC": 100.0})
    broker = Broker(exchange, "USDC", sleep=lambda _s: None)
    broker.load_markets(["ETH"])
    buy = broker.fill_from_order(order_with_fee(100.0, 0.001, "ETH"), "ETH/USDC", "buy", "x")
    sell = broker.fill_from_order(order_with_fee(100.0, 0.1, "USDC"), "ETH/USDC", "sell", "x")
    assert buy.fee_other == 0.0 and buy.fee_value == pytest.approx(0.001 * 100.0)
    assert sell.fee_other == 0.0 and sell.fee_value == pytest.approx(0.1)


# ---------------------------------------------------------------- Buchung im Bot

def test_bnb_fees_count_as_costs_of_the_trade_and_reduce_profit(tmp_path):
    exchange = bnb_market()
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock)
    pos = bot.st["positions"]["ETH/USDC"]
    paid_buy = bot.st["fees_paid"]
    assert paid_buy > 0 and bot.st["fees_external"] == pytest.approx(paid_buy)       # alles aus dem BNB-Guthaben
    assert pos["cost"] == pytest.approx(exchange.orders["1"]["cost"] + paid_buy)      # Gebühr gehört zu den Kosten
    assert pos["amount"] == pytest.approx(exchange.balances["ETH"])                   # Coins vollständig (kein Abzug)
    assert telegram.any("BNB ≈") and not telegram.any("e-05")
    bot.close_position("ETH/USDC", "Test")
    trade = bot.st["closed"][-1]
    assert bot.st["fees_external"] > paid_buy
    assert trade["pnl"] == pytest.approx(trade["proceeds"] - trade["cost"], abs=1e-5)   # Datensatz rundet auf 6 Stellen
    assert trade["proceeds"] == pytest.approx(exchange.orders["2"]["cost"] - (bot.st["fees_external"] - paid_buy))
    # „seit Start“ enthält die Gebühren, die nicht im Kapital (USDC + Positionen) stehen
    bot.refresh()
    text = "\n".join(bot.summary_lines())
    start = bot.st["start_equity"]
    profit = bot.equity - start - bot.st["fees_external"]
    assert f"seit Start −{abs(profit):.2f}".replace(".", ",") in text or f"seit Start +{profit:.2f}".replace(".", ",") in text
    assert "davon" in text and "aus dem BNB-Guthaben" in text


# ---------------------------------------------------------------- 4h-Bericht

def test_report_after_a_buy_lists_the_held_coin_not_as_next_breakout(tmp_path):
    exchange = market(signals=("ETH/USDC",))
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock)
    assert "ETH/USDC" in bot.st["positions"]
    telegram.sent.clear()
    bot.scan_state = (0, set(), [])
    bot.st["last_signal_candle"] = 0
    # nächste Prüfung: kein neues Signal, ETH wird gehalten
    exchange.candles["ETH/USDC"] = trend_candles(SIGNAL_TS, breakout=False, start=50.0)
    exchange.prices["ETH/USDC"] = last_close(exchange.candles["ETH/USDC"], bot.now_ms())
    bot.check_entries()
    report = "\n".join(t for t in telegram.sent if "4h-Prüfung" in t)
    assert "Am nächsten dran: ETH" not in report and "ETH (noch" not in report
    assert "Im Bestand: ETH" in report


def test_markt_command_marks_held_coins(tmp_path):
    exchange = market(signals=("ETH/USDC",))
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock)
    telegram.sent.clear()
    bot.handle("/markt")
    text = telegram.last()
    assert "ETH: im Bestand (siehe /status)" in text and "ETH: noch +" not in text


def test_fees_in_coin_or_usdc_leave_the_display_unchanged(tmp_path):
    exchange = market()                                      # Gebühren wie bisher in Coin (Kauf) und USDC (Verkauf)
    bot, telegram, clock = started(tmp_path, exchange)
    scan_now(bot, clock)
    assert bot.st["fees_paid"] > 0 and bot.st["fees_external"] == 0.0
    assert "davon" not in "\n".join(bot.summary_lines())
