"""
Zugriff auf Binance Spot über ccxt – und eine Simulation mit derselben Schnittstelle (Papiermodus und Tests).

Der Bot spricht nur mit `Broker`. Ob dahinter das echte Binance-Konto oder die Simulation steckt, entscheidet allein,
welcher Client übergeben wird. So läuft im Papiermodus und in den Tests exakt derselbe Order-Code wie mit Echtgeld.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any, Callable, Optional

import ccxt

log = logging.getLogger("newtry.exchange")


class ExchangeProblem(Exception):
    """Vorübergehendes Problem (Netz, Börse überlastet). Später erneut versuchen."""


class OrderUnclear(ExchangeProblem):
    """Eine Order wurde abgeschickt, ihr Ergebnis ist aber unbekannt. Vor jeder neuen Order klären."""


class AuthProblem(Exception):
    """Schlüssel ungültig, gesperrt oder ohne Handelsrecht. Hier muss ein Mensch handeln."""


class OrderRejected(Exception):
    """Die Börse lehnt die Order ab (zu klein, zu wenig Guthaben, Markt geschlossen …)."""


@dataclass(frozen=True)
class MarketInfo:
    symbol: str
    base: str
    quote: str
    amount_step: float
    min_amount: float
    min_cost: float


@dataclass(frozen=True)
class Fill:
    order_id: str
    client_id: str
    side: str
    amount: float        # ausgeführte Menge in der Basiswährung (vor Gebühr)
    cost: float          # Gegenwert in der Quote-Währung (Menge × Kurs)
    price: float         # Durchschnittskurs
    fee_base: float      # Gebühr, die in der Basiswährung abgezogen wurde (Binance: beim Kauf)
    fee_quote: float     # Gebühr, die in der Quote-Währung abgezogen wurde (Binance: beim Verkauf)
    fee_note: str = ""   # z. B. "0,0001 BNB" oder "Gebühr geschätzt"

    @property
    def net_amount(self) -> float:
        return max(0.0, self.amount - self.fee_base)

    @property
    def fee_value(self) -> float:
        return self.fee_quote + self.fee_base * self.price


class Balances:
    def __init__(self, free: dict[str, float], total: dict[str, float]):
        self._free = free
        self._total = total

    def free(self, asset: str) -> float:
        return float(self._free.get(asset) or 0.0)

    def total(self, asset: str) -> float:
        return float(self._total.get(asset) or 0.0)

    def nonzero(self) -> dict[str, float]:
        return {asset: amount for asset, amount in sorted(self._total.items()) if amount and amount > 0}


def make_binance_client(api_key: str = "", api_secret: str = "") -> Any:
    config: dict[str, Any] = {
        "enableRateLimit": True,
        "timeout": 20_000,
        "options": {
            "defaultType": "spot",
            "fetchMarkets": {"types": ["spot"]},
            "fetchCurrencies": False,        # sonst ruft ccxt mit Schlüssel einen privaten Endpunkt auf, den wir nie brauchen
            "adjustForTimeDifference": True,
            "recvWindow": 10_000,
            "warnOnFetchOpenOrdersWithoutSymbol": False,
        },
    }
    if api_key and api_secret:
        config["apiKey"] = api_key
        config["secret"] = api_secret
    return ccxt.binance(config)


class Broker:
    def __init__(self, client: Any, quote: str, sleep: Callable[[float], None] = time.sleep):
        self.client = client
        self.quote = quote
        self.markets: dict[str, MarketInfo] = {}
        self._sleep = sleep

    # ------------------------------------------------------------------ Lesen (mit Wiederholung)

    def _call(self, what: str, fn: Callable[..., Any], *args: Any, retries: int = 3) -> Any:
        delay = 2.0
        for attempt in range(1, retries + 1):
            try:
                return fn(*args)
            except ccxt.AuthenticationError as exc:      # auch PermissionDenied, AccountSuspended
                raise AuthProblem(f"{what}: {exc}") from exc
            except ccxt.NetworkError as exc:             # Zeitüberschreitung, Überlastung, Wartung, Uhrzeit
                if attempt == retries:
                    raise ExchangeProblem(f"{what}: {type(exc).__name__}: {exc}") from exc
                log.warning("%s fehlgeschlagen (%s), neuer Versuch in %.0f s", what, type(exc).__name__, delay)
                self._sleep(delay)
                delay *= 2.5
            except ccxt.ExchangeError as exc:
                raise ExchangeProblem(f"{what}: {type(exc).__name__}: {exc}") from exc
        raise ExchangeProblem(what)  # pragma: no cover

    def load_markets(self, coins: tuple[str, ...] | list[str]) -> tuple[list[str], list[str]]:
        markets = self._call("Märkte laden", self.client.load_markets)
        found, missing = [], []
        for coin in coins:
            symbol = f"{coin}/{self.quote}"
            market = markets.get(symbol)
            if not market or market.get("spot") is False or market.get("active") is False:
                missing.append(coin)
                continue
            self.markets[symbol] = self._market_info(market)
            found.append(symbol)
        return found, missing

    def ensure_market(self, symbol: str) -> Optional[MarketInfo]:
        if symbol not in self.markets:
            market = (getattr(self.client, "markets", None) or {}).get(symbol)
            if market:
                self.markets[symbol] = self._market_info(market)
        return self.markets.get(symbol)

    def _market_info(self, market: dict[str, Any]) -> MarketInfo:
        limits = market.get("limits") or {}
        step = (market.get("precision") or {}).get("amount") or 0.0
        if getattr(self.client, "precisionMode", ccxt.TICK_SIZE) == ccxt.DECIMAL_PLACES:
            step = 10.0 ** -int(step)
        return MarketInfo(
            symbol=market["symbol"],
            base=market["base"],
            quote=market["quote"],
            amount_step=float(step or 0.0),
            min_amount=float((limits.get("amount") or {}).get("min") or 0.0),
            min_cost=float((limits.get("cost") or {}).get("min") or 5.0),
        )

    def fetch_candles(self, symbol: str, timeframe: str, limit: int) -> list[tuple]:
        rows = self._call(f"Kerzen {symbol}", self.client.fetch_ohlcv, symbol, timeframe, None, limit)
        return [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5] or 0.0)) for r in rows]

    def fetch_prices(self, symbols: list[str]) -> dict[str, float]:
        if not symbols:
            return {}
        tickers = self._call("Kurse", self.client.fetch_tickers, list(symbols))
        prices: dict[str, float] = {}
        for symbol in symbols:
            ticker = tickers.get(symbol) or {}
            price = ticker.get("last") or ticker.get("close") or ticker.get("bid")
            if price:
                prices[symbol] = float(price)
        return prices

    def balances(self) -> Balances:
        raw = self._call("Kontostand", self.client.fetch_balance)
        free = {k: float(v or 0.0) for k, v in (raw.get("free") or {}).items() if isinstance(v, (int, float))}
        total = {k: float(v or 0.0) for k, v in (raw.get("total") or {}).items() if isinstance(v, (int, float))}
        return Balances(free, total)

    def open_orders(self) -> list[dict[str, Any]]:
        return list(self._call("Offene Orders", self.client.fetch_open_orders) or [])

    def round_amount(self, symbol: str, amount: float) -> float:
        """Menge auf die erlaubte Schrittweite ABrunden (wie Binance es verlangt)."""
        if amount <= 0:
            return 0.0
        try:
            return float(self.client.amount_to_precision(symbol, amount))
        except Exception:
            return 0.0

    # ------------------------------------------------------------------ Orders

    def market_order(self, symbol: str, side: str, amount: float, client_id: str) -> Fill:
        """
        Market-Order. Bei einer Netz-Störung wird über die eigene Order-Nummer (client_id) nachgesehen, ob die Order
        trotzdem ausgeführt wurde. So entsteht nie eine doppelte Order.
        """
        params = {"newClientOrderId": client_id}
        try:
            order = self.client.create_order(symbol, "market", side, amount, None, params)
        except ccxt.InsufficientFunds as exc:
            raise OrderRejected(f"Zu wenig Guthaben: {exc}") from exc
        except ccxt.InvalidOrder as exc:
            raise OrderRejected(f"Order ungültig: {exc}") from exc
        except ccxt.AuthenticationError as exc:
            raise AuthProblem(f"Order {symbol}: {exc}") from exc
        except ccxt.NetworkError as exc:
            log.warning("Order %s %s: Netzfehler (%s) – prüfe, ob sie angekommen ist", side, symbol, exc)
            order = self.find_order(symbol, client_id)
            if order is None:
                raise ExchangeProblem(f"Order {side} {symbol} wurde nicht ausgeführt ({exc})") from exc
        except ccxt.ExchangeError as exc:
            raise OrderRejected(f"Börse lehnt ab: {exc}") from exc
        order = self._complete(order, symbol)
        fill = self.fill_from_order(order, symbol, side, client_id)
        if fill.amount <= 0:
            raise OrderRejected(f"Order {side} {symbol} wurde nicht ausgeführt (Status {order.get('status')}).")
        return fill

    def find_order(self, symbol: str, client_id: str) -> Optional[dict[str, Any]]:
        """Order über die eigene Nummer suchen. None = sicher nicht vorhanden. OrderUnclear = Börse nicht erreichbar."""
        not_found = 0
        for attempt in range(5):
            try:
                return self.client.fetch_order(None, symbol, {"origClientOrderId": client_id})
            except ccxt.OrderNotFound:
                not_found += 1
                if not_found >= 3:               # dreimal „unbekannt“ im Abstand von Sekunden: sicher nicht angekommen
                    return None
            except (ccxt.NetworkError, ccxt.ExchangeError) as exc:
                log.warning("Order-Suche %s: %s", client_id, exc)
            self._sleep(2.0 * (attempt + 1))
        raise OrderUnclear(f"Ergebnis der Order {client_id} ({symbol}) ist noch unklar – Binance nicht erreichbar.")

    def _complete(self, order: dict[str, Any], symbol: str) -> dict[str, Any]:
        """Market-Orders sind bei Binance sofort fertig; fehlen Angaben, wird die Order nachgeladen."""
        for _ in range(3):
            if order.get("filled") is not None and order.get("status") in ("closed", "canceled", "expired", "rejected"):
                return order
            self._sleep(1.0)
            try:
                if order.get("id"):
                    order = self.client.fetch_order(order["id"], symbol)
            except (ccxt.NetworkError, ccxt.ExchangeError) as exc:
                log.warning("Order nachladen %s: %s", symbol, exc)
        return order

    def fill_from_order(self, order: dict[str, Any], symbol: str, side: str, client_id: str) -> Fill:
        market = self.ensure_market(symbol)
        base = market.base if market else symbol.split("/")[0]
        quote = market.quote if market else self.quote
        filled = float(order.get("filled") or 0.0)
        cost = float(order.get("cost") or 0.0)
        average = float(order.get("average") or 0.0) or (cost / filled if filled else 0.0)
        if not cost and filled and average:
            cost = filled * average
        fees = [f for f in (order.get("fees") or []) if f]
        if not fees and order.get("fee"):
            fees = [order["fee"]]
        if not fees:
            fees = [t["fee"] for t in (order.get("trades") or []) if t.get("fee")]
        fee_base = fee_quote = 0.0
        notes: list[str] = []
        known = False
        for fee in fees:
            if fee.get("cost") is None:
                continue
            known = True
            amount = float(fee["cost"])
            currency = fee.get("currency")
            if currency == base:
                fee_base += amount
            elif currency == quote:
                fee_quote += amount
            elif amount:
                notes.append(f"{amount:g} {currency}")
        if not known and filled > 0:
            # Keine Angabe: vorsichtig 0,1 % annehmen (Binance zieht sie beim Kauf vom Coin ab, beim Verkauf von USDC)
            if side == "buy":
                fee_base = filled * 0.001
            else:
                fee_quote = cost * 0.001
            notes.append("Gebühr geschätzt")
        return Fill(order_id=str(order.get("id") or ""), client_id=client_id, side=side, amount=filled, cost=cost,
                    price=average, fee_base=fee_base, fee_quote=fee_quote, fee_note=", ".join(notes))

    def api_permissions(self) -> Optional[dict[str, Any]]:
        """Rechte des API-Schlüssels (nur echtes Binance). None, wenn nicht abfragbar."""
        call = getattr(self.client, "sapi_get_account_apirestrictions", None)
        if call is None:
            return None
        try:
            return dict(call())
        except Exception as exc:  # nur zur Information – der Handel hängt nicht davon ab
            log.info("API-Rechte nicht abfragbar: %s", exc)
            return None


# ====================================================================== Simulation


def _floor_to_step(amount: float, step: float) -> float:
    if step <= 0:
        return amount
    units = (Decimal(repr(amount)) / Decimal(repr(step))).to_integral_value(rounding=ROUND_DOWN)
    return float(units * Decimal(repr(step)))


class SimulatedExchange:
    """
    Spielt Binance Spot nach – mit der Schnittstelle von ccxt: Market-Orders zum aktuellen Kurs plus Schlupf,
    0,1 % Gebühr (beim Kauf vom Coin, beim Verkauf von der Quote-Währung abgezogen), Schrittweiten und Mindestgröße.
    Unterklassen liefern `markets`, `fetch_ohlcv`, `fetch_tickers` und `current_price`.
    """

    precisionMode = ccxt.TICK_SIZE

    def __init__(self, balances: dict[str, float], fee_rate: float = 0.001, slippage: float = 0.0005,
                 wallet_path: Optional[Path] = None):
        self.wallet_path = wallet_path
        self.balances: dict[str, float] = dict(balances)
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.markets: dict[str, dict[str, Any]] = {}
        self.orders: dict[str, dict[str, Any]] = {}
        self.by_client_id: dict[str, str] = {}
        self._next_id = 1
        if wallet_path and wallet_path.exists():
            saved = json.loads(wallet_path.read_text(encoding="utf-8"))
            self.balances = {k: float(v) for k, v in saved.get("balances", {}).items()}
            self._next_id = int(saved.get("next_id", 1))

    def current_price(self, symbol: str) -> float:  # pragma: no cover - Unterklassen
        raise NotImplementedError

    def load_markets(self) -> dict[str, dict[str, Any]]:
        return self.markets

    def amount_to_precision(self, symbol: str, amount: float) -> str:
        step = float(self.markets[symbol]["precision"]["amount"])
        value = _floor_to_step(float(amount), step)
        if value <= 0:
            raise ccxt.InvalidOrder(f"Menge {amount} kleiner als die Schrittweite {step}")
        return repr(value)

    def fetch_balance(self) -> dict[str, Any]:
        free = {k: v for k, v in self.balances.items()}
        return {"free": free, "used": {k: 0.0 for k in free}, "total": dict(free)}

    def fetch_open_orders(self, symbol: Any = None, since: Any = None, limit: Any = None,
                          params: Any = None) -> list[dict[str, Any]]:
        return []

    def create_order(self, symbol: str, type: str, side: str, amount: float, price: Any = None,
                     params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        params = params or {}
        if type != "market":
            raise ccxt.InvalidOrder("Die Simulation kennt nur Market-Orders.")
        market = self.markets.get(symbol)
        if not market:
            raise ccxt.BadSymbol(symbol)
        amount = float(self.amount_to_precision(symbol, amount))
        last = self.current_price(symbol)
        fill_price = last * (1 + self.slippage) if side == "buy" else last * (1 - self.slippage)
        cost = amount * fill_price
        min_cost = float(((market.get("limits") or {}).get("cost") or {}).get("min") or 5.0)
        if cost < min_cost:
            raise ccxt.InvalidOrder(f"Filter failure: NOTIONAL ({cost:.2f} < {min_cost})")
        base, quote = market["base"], market["quote"]
        if side == "buy":
            if self.balances.get(quote, 0.0) < cost - 1e-9:
                raise ccxt.InsufficientFunds(f"Account has insufficient balance ({quote})")
            fee = amount * self.fee_rate
            self.balances[quote] = self.balances.get(quote, 0.0) - cost
            self.balances[base] = self.balances.get(base, 0.0) + amount - fee
            fee_currency = base
        else:
            if self.balances.get(base, 0.0) < amount - 1e-12:
                raise ccxt.InsufficientFunds(f"Account has insufficient balance ({base})")
            fee = cost * self.fee_rate
            self.balances[base] = self.balances.get(base, 0.0) - amount
            self.balances[quote] = self.balances.get(quote, 0.0) + cost - fee
            fee_currency = quote
        order_id = str(self._next_id)
        self._next_id += 1
        fee_entry = {"cost": fee, "currency": fee_currency}
        order = {
            "id": order_id, "clientOrderId": params.get("newClientOrderId"), "symbol": symbol, "type": "market",
            "side": side, "status": "closed", "amount": amount, "filled": amount, "remaining": 0.0, "cost": cost,
            "average": fill_price, "price": fill_price, "fee": fee_entry, "fees": [dict(fee_entry)],
            "timestamp": int(time.time() * 1000),
        }
        self.orders[order_id] = order
        if order["clientOrderId"]:
            self.by_client_id[order["clientOrderId"]] = order_id
        self._save()
        return dict(order)

    def fetch_order(self, id: Optional[str], symbol: Optional[str] = None,
                    params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        client_id = (params or {}).get("origClientOrderId")
        order_id = self.by_client_id.get(client_id) if client_id else id
        if order_id not in self.orders:
            raise ccxt.OrderNotFound(f"Order does not exist ({client_id or id})")
        return dict(self.orders[order_id])

    def _save(self) -> None:
        if not self.wallet_path:
            return
        self.wallet_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.wallet_path.with_suffix(".tmp")
        temp.write_text(json.dumps({"balances": self.balances, "next_id": self._next_id}, indent=1), encoding="utf-8")
        os.replace(temp, self.wallet_path)


class PaperExchange(SimulatedExchange):
    """Papiermodus: echte Binance-Kurse (öffentliche Daten, ohne Schlüssel), simuliertes Konto in data/paper_wallet.json."""

    def __init__(self, quote: str, start_balance: float, wallet_path: Path, public_client: Any = None):
        super().__init__({quote: start_balance}, wallet_path=wallet_path)
        self.public = public_client or make_binance_client()

    def load_markets(self) -> dict[str, dict[str, Any]]:
        self.markets = self.public.load_markets()
        return self.markets

    def amount_to_precision(self, symbol: str, amount: float) -> str:
        return self.public.amount_to_precision(symbol, amount)

    def fetch_ohlcv(self, symbol: str, timeframe: str = "4h", since: Any = None, limit: Any = None) -> list:
        return self.public.fetch_ohlcv(symbol, timeframe, since, limit)

    def fetch_tickers(self, symbols: Any = None) -> dict[str, Any]:
        return self.public.fetch_tickers(symbols)

    def current_price(self, symbol: str) -> float:
        ticker = self.public.fetch_ticker(symbol)
        return float(ticker.get("last") or ticker.get("close"))
