"""Testhelfer: simulierte Börse (wie Binance), Telegram-Attrappe, steuerbare Uhr, Kerzen-Generator."""
from __future__ import annotations

import dataclasses
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import ccxt

import strategy
from bot import Bot
from config import Settings
from exchange import Broker, SimulatedExchange
from state import StateStore

TF = strategy.TIMEFRAME_MS
# Schluss der Signal-Kerze: Samstag, 07.11.2026, 20:00 UTC (21:00 deutscher Zeit)
SIGNAL_CLOSE_MS = int(datetime(2026, 11, 7, 20, 0, tzinfo=timezone.utc).timestamp() * 1000)
SIGNAL_TS = SIGNAL_CLOSE_MS - TF


class Clock:
    def __init__(self, ms: int):
        self.t = ms / 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds

    def set_ms(self, ms: int) -> None:
        self.t = ms / 1000.0


class FakeExchange(SimulatedExchange):
    def __init__(self, balances: dict[str, float], prices: dict[str, float], step: float = 0.0001,
                 min_cost: float = 5.0):
        super().__init__(balances, slippage=0.0)
        self.prices = dict(prices)
        self.candles: dict[str, list[list[float]]] = {}
        self.timeout_after_fill = False
        self.timeout_before_fill = False
        self.create_calls = 0
        for symbol in prices:
            base, quote = symbol.split("/")
            self.markets[symbol] = {
                "symbol": symbol, "base": base, "quote": quote, "active": True, "spot": True,
                "precision": {"amount": step, "price": 0.01},
                "limits": {"cost": {"min": min_cost}, "amount": {"min": step}},
            }

    def current_price(self, symbol: str) -> float:
        return self.prices[symbol]

    def fetch_ohlcv(self, symbol: str, timeframe: str = "4h", since: Any = None, limit: Any = None) -> list:
        rows = self.candles.get(symbol, [])
        return [list(r) for r in (rows[-limit:] if limit else rows)]

    def fetch_tickers(self, symbols: Any = None) -> dict[str, Any]:
        wanted = symbols or list(self.prices)
        return {s: {"symbol": s, "last": self.prices[s]} for s in wanted if s in self.prices}

    def create_order(self, symbol: str, type: str, side: str, amount: float, price: Any = None,
                     params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.create_calls += 1
        if self.timeout_before_fill:
            raise ccxt.RequestTimeout("binance POST /api/v3/order timed out")
        order = super().create_order(symbol, type, side, amount, price, params)
        if self.timeout_after_fill:
            self.timeout_after_fill = False
            raise ccxt.RequestTimeout("binance POST /api/v3/order timed out")
        return order


class FakeTelegram:
    enabled = True

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.silent: list[bool] = []
        self.inbox: list[str] = []

    def send(self, text: str, silent: bool = False) -> bool:
        self.sent.append(text)
        self.silent.append(silent)
        return True

    def prepare(self, commands: list[tuple[str, str]]) -> str:
        return "testbot"

    def poll(self, timeout: float) -> list[str]:
        out, self.inbox = self.inbox, []
        return out

    def last(self) -> str:
        return self.sent[-1] if self.sent else ""

    def any(self, fragment: str) -> bool:
        return any(fragment in text for text in self.sent)


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    base = Settings(
        mode="live", api_key="k", api_secret="s", telegram_token="t", telegram_chat_id="1", quote="USDC",
        coins=("ETH", "BTC", "SOL", "XRP"), risk_per_trade_pct=1.0, max_positions=3, max_position_pct=33.0,
        daily_loss_limit_pct=6.0, max_drawdown_pct=25.0, selftest_trade=False, scan_reports=True, report_hour=9,
        timezone="Europe/Berlin", paper_start_balance=150.0, data_dir=tmp_path / "data",
    )
    return dataclasses.replace(base, **overrides)


def make_bot(tmp_path: Path, exchange: FakeExchange, clock: Clock, **overrides: Any) -> tuple[Bot, FakeTelegram]:
    settings = make_settings(tmp_path, **overrides)
    telegram = FakeTelegram()
    bot = Bot(settings, Broker(exchange, settings.quote, sleep=lambda _s: None), telegram,
              StateStore(settings.data_dir / "state.json"), clock=clock)
    return bot, telegram


def trend_candles(last_open_ts: int, breakout: bool = True, n: int = 1000, start: float = 100.0,
                  drift: float = 0.0006, include_open: bool = True) -> list[list[float]]:
    """Aufwärtstrend mit Wellen. breakout=True: die letzte Kerze schließt 1 % über dem Hoch der vorherigen 100."""
    candles: list[list[float]] = []
    price = start
    for i in range(n):
        ts = last_open_ts - (n - 1 - i) * TF
        open_ = price
        price = price * (1 + drift + 0.006 * math.sin(i / 6.0))
        close = price
        candles.append([ts, open_, max(open_, close) * 1.005, min(open_, close) * 0.995, close, 1000.0])
    prior_high = max(c[2] for c in candles[-101:-1])
    last = candles[-1]
    if breakout:
        last[4] = prior_high * 1.01
        last[2] = last[4] * 1.002
    else:
        last[4] = prior_high * 0.97
        last[2] = prior_high * 0.98
        last[3] = min(last[3], last[4] * 0.995)
    if include_open:
        candles.append([last_open_ts + TF, last[4], last[4] * 1.001, last[4] * 0.999, last[4], 10.0])
    return candles


def last_close(candles: list[list[float]], now_ms: int) -> float:
    return strategy.closed_candles(candles, now_ms)[-1][4]
