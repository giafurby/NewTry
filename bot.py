#!/usr/bin/env python3
"""
NewTry – schlanker Handelsbot für Binance Spot.

  Dauerbetrieb (systemd):           .venv/bin/python bot.py
  Startklar-Prüfung (handelt nicht): .venv/bin/python bot.py --check

Ablauf: alle 10 Sekunden Telegram-Befehle und Kurse der offenen Positionen prüfen (Stop, Ziel, Zeit), jede Minute
Kontostand und Verlustgrenzen, und direkt nach jedem 4h-Kerzenschluss alle Coins auf ein Kaufsignal prüfen.
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import secrets
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

import strategy
from config import ConfigError, Settings, load_settings
from exchange import (AuthProblem, Broker, ExchangeProblem, Fill, OrderRejected, OrderUnclear, PaperExchange,
                      make_binance_client)
from notifier import Telegram
from state import StateStore

log = logging.getLogger("newtry")

LOOP_SECONDS = 10            # Takt der Hauptschleife (so lange wartet die Telegram-Abfrage)
BALANCE_SECONDS = 60         # Kontostand, Verlustgrenzen und Abgleich
SCAN_DELAY_MS = 20_000       # nach dem Kerzenschluss kurz warten, bis Binance die Kerze fertig hat
ALERT_REPEAT_SECONDS = 1800  # derselbe Fehler höchstens alle 30 Minuten per Telegram
OUTAGE_ALERT_SECONDS = 300   # Börse erst melden, wenn sie länger als 5 Minuten nicht erreichbar ist
MIN_ORDER_BUFFER = 1.15      # 15 % Abstand zum Binance-Minimum je Order
CASH_BUFFER = 0.98           # höchstens 98 % des freien Guthabens in eine Order
MAX_RISK_FRACTION = 0.03     # die Mindest-Ordergröße nur nutzen, wenn der Trade dann höchstens 3 % riskiert
SELFTEST_COINS = ("ETH", "BTC", "SOL", "XRP", "BNB")

COMMANDS = [
    ("status", "Kapital, Positionen und Grenzen"),
    ("trades", "letzte abgeschlossene Trades"),
    ("markt", "wie nah sind die Coins am Kaufsignal?"),
    ("pause", "keine neuen Käufe (Positionen laufen weiter)"),
    ("weiter", "wieder kaufen (hebt Pause und Notstopp auf)"),
    ("notverkauf", "alle Positionen sofort verkaufen"),
    ("hilfe", "alle Befehle"),
]


# ====================================================================== Zahlen auf Deutsch


def de(value: float, digits: int = 2) -> str:
    text = f"{value:,.{digits}f}"
    return text.replace(",", "\0").replace(".", ",").replace("\0", ".")


def signed(value: float, digits: int = 2) -> str:
    return ("+" if value >= 0 else "−") + de(abs(value), digits)


def pct(value: float, digits: int = 1) -> str:
    return signed(value, digits) + " %"


def price_text(value: float) -> str:
    digits = 2 if value >= 1000 else 3 if value >= 10 else 4 if value >= 1 else 6 if value >= 0.01 else 8
    return de(value, digits)


def qty(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".").replace(".", ",")


def coin(symbol: str) -> str:
    return symbol.split("/")[0]


# ====================================================================== Bot


class Bot:
    def __init__(self, settings: Settings, broker: Broker, telegram: Telegram, store: StateStore,
                 clock: Callable[[], float] = time.time):
        self.s = settings
        self.broker = broker
        self.tg = telegram
        self.store = store
        self.st: dict[str, Any] = store.data
        self.clock = clock
        self.tz = ZoneInfo(settings.timezone)
        self.q = settings.quote
        self.tag = "💶 ECHTGELD" if settings.live else "📄 PAPIER"
        self.symbols: list[str] = []
        self.missing: list[str] = []
        self.running = True
        self.balances: Any = None
        self.quote_free = 0.0
        self.quote_total = 0.0
        self.equity = 0.0
        self.prices: dict[str, float] = {}
        self.last_balance_check = 0.0
        self.scan_state: tuple[int, set[str], list[strategy.Check]] = (0, set(), [])
        self.scan_notes: dict[str, str] = {}
        self.alert_times: dict[str, float] = {}
        self.outage_since: Optional[float] = None
        self.confirm_until = 0.0
        self.gone_counts: dict[str, int] = {}

    # ------------------------------------------------------------------ Zeit

    def now_ms(self) -> int:
        return int(self.clock() * 1000)

    def local(self, ms: Optional[int] = None) -> datetime:
        return datetime.fromtimestamp((self.now_ms() if ms is None else ms) / 1000, tz=self.tz)

    def when(self, ms: int) -> str:
        return self.local(ms).strftime("%d.%m. %H:%M")

    def iso(self) -> str:
        return datetime.fromtimestamp(self.clock(), tz=timezone.utc).isoformat(timespec="seconds")

    def next_close_ms(self) -> int:
        tf = strategy.TIMEFRAME_MS
        return (self.now_ms() // tf + 1) * tf

    def close_hours(self) -> str:
        tf = strategy.TIMEFRAME_MS
        hours = sorted({self.local(self.next_close_ms() + k * tf).hour for k in range(6)})
        return ", ".join(f"{h:02d}" for h in hours)

    def client_id(self, side: str) -> str:
        return f"nt{side}{self.now_ms()}{secrets.token_hex(3)}"

    # ------------------------------------------------------------------ Start

    def startup(self) -> None:
        self.symbols, self.missing = self.broker.load_markets(self.s.coins)
        if not self.symbols:
            raise ConfigError(f"Keiner der Coins hat bei Binance einen {self.q}-Markt. QUOTE und COINS in der .env prüfen.")
        for symbol in list(self.st["positions"]):
            if not self.broker.ensure_market(symbol):
                log.error("Markt %s für eine offene Position nicht gefunden.", symbol)
        self.resolve_pending()
        self.refresh()
        st = self.st
        if st["start_equity"] is None:
            st["start_equity"] = round(self.equity, 2)
            st["started_at"] = self.iso()
            st["peak_equity"] = self.equity
        if st["last_report_day"] is None:
            st["last_report_day"] = self.local().date().isoformat()
        self.roll_day()
        self.store.save()
        self.tg.prepare(COMMANDS)
        self.tg.send(self.start_message())
        self.warn_foreign_orders()
        selftest_open = any(p.get("selftest") for p in st["positions"].values())   # wird in check_exits verkauft
        if self.s.live and self.s.selftest_trade and not st["selftest_done"] and not selftest_open:
            try:
                self.selftest()
            except Exception as exc:                       # der Test darf den Start nie verhindern
                log.exception("Funktionstest fehlgeschlagen")
                self.tg.send(f"⚠️ Funktionstest fehlgeschlagen ({type(exc).__name__}: {exc}). Der Bot läuft trotzdem; "
                             "der Test wird beim nächsten Start wiederholt.")

    def start_message(self) -> str:
        s, st = self.s, self.st
        lines = [
            f"🤖 NewTry-Bot gestartet · {self.tag}",
            f"Kapital: {de(self.equity)} {self.q} (frei {de(self.quote_free)} {self.q})",
            "Regel: 4h-Ausbruch über das Hoch der letzten 100 Kerzen bei Kurs über der EMA 200 · "
            "Stop 2 ATR · Ziel 15 ATR · max. 20 Tage",
            f"Coins: {len(self.symbols)} beobachtet" + (f" (ohne {self.q}-Markt: {', '.join(self.missing)})"
                                                         if self.missing else ""),
            f"Risiko je Trade: {de(s.risk_per_trade_pct, 1)} % (≈ {de(self.equity * s.risk_per_trade_pct / 100)} "
            f"{self.q}) · max. {s.max_positions} Positionen · Tageslimit −{de(s.daily_loss_limit_pct, 0)} % · "
            f"Notstopp −{de(s.max_drawdown_pct, 0)} %",
        ]
        if st["positions"]:
            lines.append(f"Offene Positionen: {', '.join(coin(x) for x in st['positions'])}")
        if st["halted"]:
            lines.append(f"🛑 Notstopp aktiv ({st['halt_reason']}). Wieder kaufen: /weiter")
        elif st["paused"]:
            lines.append("⏸ Pausiert – keine neuen Käufe. Wieder kaufen: /weiter")
        if self.quote_free < 7:
            others = {a: v for a, v in (self.balances.nonzero() if self.balances else {}).items() if a != self.q}
            lines.append(f"⚠️ Nur {de(self.quote_free)} {self.q} frei – je Kauf braucht der Bot mindestens etwa 6 "
                         f"{self.q}. Der Bot kauft nur mit {self.q}."
                         + (f" Weitere Guthaben: {', '.join(f'{a} {qty(v)}' for a, v in others.items())}." if others else ""))
        lines.append(f"Nächste Prüfung: {self.when(self.next_close_ms())} (immer um {self.close_hours()} Uhr)")
        lines.append("Befehle: /status /markt /trades /pause /weiter /notverkauf /hilfe")
        return "\n".join(lines)

    def warn_foreign_orders(self) -> None:
        try:
            orders = self.broker.open_orders()
        except (ExchangeProblem, AuthProblem) as exc:
            log.warning("Offene Orders nicht abrufbar: %s", exc)
            return
        if not orders:
            return
        listed = "; ".join(f"{o.get('symbol')} {o.get('side')} {o.get('type')} {qty(float(o.get('amount') or 0))}"
                           for o in orders[:5])
        self.tg.send(f"⚠️ Auf dem Konto liegen {len(orders)} offene Orders, die nicht von diesem Bot stammen "
                     f"(vermutlich vom alten Bot): {listed}. Sie binden Guthaben. Wenn du sie nicht brauchst, "
                     "storniere sie in der Binance-App unter Orders → Offene Orders.")

    # ------------------------------------------------------------------ Hauptschleife

    def run(self) -> None:
        while self.running:
            for text in self.tg.poll(LOOP_SECONDS):
                try:
                    self.handle(text)
                except Exception as exc:
                    log.exception("Befehl %r fehlgeschlagen", text)
                    self.tg.send(f"❗ Befehl fehlgeschlagen: {type(exc).__name__}: {exc}")
            if not self.running:
                break
            try:
                self.tick()
                self.outage_since = None
            except AuthProblem as exc:
                self.alert("auth", f"❗ Binance lehnt den API-Schlüssel ab: {exc}\nPrüfe in der Binance-App unter "
                                   "API-Verwaltung: Schlüssel aktiv, Spot-Handel erlaubt, IP-Freigabe für den Server. "
                                   "Der Bot versucht es weiter.")
            except ExchangeProblem as exc:
                now = self.clock()
                self.outage_since = self.outage_since or now
                log.warning("Börse: %s", exc)
                if now - self.outage_since >= OUTAGE_ALERT_SECONDS:
                    self.alert("exchange", f"⚠️ Binance seit {int((now - self.outage_since) / 60)} Minuten nicht "
                                           f"erreichbar ({exc}). Ich versuche es weiter.")
            except Exception as exc:
                log.exception("Unerwarteter Fehler")
                self.alert(f"bug-{type(exc).__name__}", f"❗ Unerwarteter Fehler: {type(exc).__name__}: {exc}. "
                                                        "Der Bot läuft weiter.")
        self.store.save()
        self.tg.send(f"⏹ NewTry-Bot angehalten ({self.tag}). Offene Positionen bleiben stehen und werden nach "
                     "dem Neustart weiter überwacht.")

    def tick(self) -> None:
        if self.st.get("pending") and not self.resolve_pending():
            return
        if self.st["positions"]:
            self.check_exits()
        if self.clock() - self.last_balance_check >= BALANCE_SECONDS:
            self.refresh()
            self.reconcile()
            self.check_limits()
            self.store.save()
        self.check_entries()
        self.daily_report()
        self.heartbeat()

    def alert(self, key: str, text: str) -> None:
        now = self.clock()
        if now - self.alert_times.get(key, -1e12) < ALERT_REPEAT_SECONDS:
            log.warning("%s", text)
            return
        self.alert_times[key] = now
        self.tg.send(text)

    def heartbeat(self) -> None:
        try:
            path = self.s.data_dir / "heartbeat"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.iso(), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------------ Konto und Grenzen

    def refresh(self, after_trade: bool = False) -> None:
        """Kontostand holen und Kapital berechnen. Ändert sich das Guthaben ohne Trade, war es eine Ein-/Auszahlung."""
        balances = self.broker.balances()
        self.balances = balances
        self.quote_free = balances.free(self.q)
        self.quote_total = balances.total(self.q)
        positions = self.st["positions"]
        if positions:
            try:
                self.prices.update(self.broker.fetch_prices(list(positions)))
            except ExchangeProblem as exc:
                log.warning("Kurse für die Kapitalberechnung fehlen: %s", exc)
        self.recompute_equity()
        last = self.st.get("last_quote_balance")
        if not after_trade and last is not None:
            flow = self.quote_total - float(last)
            if abs(flow) >= max(1.0, 0.005 * max(self.equity, 1.0)):
                self.record_flow(flow)
        self.st["last_quote_balance"] = self.quote_total
        self.last_balance_check = self.clock()

    def recompute_equity(self) -> None:
        value = sum(p["amount"] * self.prices.get(s, p["entry_price"]) for s, p in self.st["positions"].items())
        self.equity = self.quote_total + value

    def record_flow(self, flow: float) -> None:
        st = self.st
        for key in ("peak_equity", "day_start_equity"):
            if st.get(key) is not None:
                st[key] = max(0.0, float(st[key]) + flow)
        st["net_deposits"] = float(st.get("net_deposits") or 0.0) + flow
        label = "💶 Einzahlung" if flow > 0 else "💸 Auszahlung"
        self.tg.send(f"{label} erkannt: {signed(flow)} {self.q}. Zählt nicht als Gewinn oder Verlust.")

    def roll_day(self) -> None:
        today = self.local().date().isoformat()
        if self.st["day"] != today:
            self.st["day"] = today
            self.st["day_start_equity"] = self.equity
            self.st["day_limit_hit"] = False

    def check_limits(self) -> None:
        st, s = self.st, self.s
        self.roll_day()
        st["peak_equity"] = max(float(st["peak_equity"] or 0.0), self.equity)
        floor = st["peak_equity"] * (1 - s.max_drawdown_pct / 100)
        if not st["halted"] and self.equity < floor:
            self.emergency_stop(f"Kapital {de(self.equity)} {self.q} liegt mehr als {de(s.max_drawdown_pct, 0)} % "
                                f"unter dem Höchststand {de(st['peak_equity'])} {self.q}")
            return
        day_floor = float(st["day_start_equity"] or self.equity) * (1 - s.daily_loss_limit_pct / 100)
        if not st["day_limit_hit"] and self.equity < day_floor:
            st["day_limit_hit"] = True
            self.tg.send(f"⚠️ Tageslimit erreicht: Kapital {de(self.equity)} {self.q}, Tagesbeginn "
                         f"{de(st['day_start_equity'])} {self.q}. Heute keine neuen Käufe; offene Positionen behalten "
                         "ihren Stop. Morgen geht es automatisch weiter.")

    def emergency_stop(self, reason: str) -> None:
        self.st["halted"] = True
        self.st["halt_reason"] = reason
        self.store.save()
        self.tg.send(f"🛑 NOTSTOPP: {reason}.\nIch verkaufe alle Positionen und kaufe nichts mehr. "
                     "Wieder starten: /weiter")
        for symbol in list(self.st["positions"]):
            self.close_position(symbol, "Notstopp")

    def reconcile(self) -> None:
        """Positionen, deren Coins nicht mehr auf dem Konto liegen (z. B. von Hand verkauft), ausbuchen."""
        if self.balances is None:
            return
        for symbol, pos in list(self.st["positions"].items()):
            market = self.broker.ensure_market(symbol)
            held = self.balances.total(market.base if market else coin(symbol))
            if held >= pos["amount"] * 0.5:
                self.gone_counts.pop(symbol, None)
                continue
            self.gone_counts[symbol] = self.gone_counts.get(symbol, 0) + 1
            if self.gone_counts[symbol] < 2:      # erst beim zweiten Mal in Folge – schützt vor Aussetzern
                continue
            self.gone_counts.pop(symbol, None)
            mark = self.prices.get(symbol, pos["entry_price"])
            self.book_out(symbol, pos, "außerhalb des Bots verkauft (geschätzt zum aktuellen Kurs)", mark,
                          sold_outside=True)
            self.tg.send(f"ℹ️ {coin(symbol)}: Die Coins der Bot-Position liegen nicht mehr auf dem Konto (von Hand "
                         "verkauft oder abgehoben?). Position ausgebucht, Kapital-Rechnung korrigiert.")

    # ------------------------------------------------------------------ Offene Orders nach Absturz klären

    def resolve_pending(self) -> bool:
        pending = self.st.get("pending")
        if not pending:
            return True
        try:
            order = self.broker.find_order(pending["symbol"], pending["client_id"])
        except OrderUnclear as exc:
            log.warning("%s", exc)
            return False
        if order is None or float(order.get("filled") or 0.0) <= 0:
            log.info("Order %s ist nie ausgeführt worden – erledigt.", pending["client_id"])
            self.st["pending"] = None
            self.store.save()
            return True
        fill = self.broker.fill_from_order(order, pending["symbol"], pending["side"], pending["client_id"])
        log.warning("Order %s nachgebucht (%s %s).", pending["client_id"], pending["side"], pending["symbol"])
        if pending["side"] == "buy":
            self.book_buy(fill, pending)
        elif pending["symbol"] in self.st["positions"]:
            self.book_sell(pending["symbol"], fill, pending.get("reason") or "Verkauf")
        else:
            self.st["pending"] = None
            self.store.save()
        return True

    # ------------------------------------------------------------------ Verkaufen

    def check_exits(self) -> None:
        positions = self.st["positions"]
        prices = self.broker.fetch_prices(list(positions))
        self.prices.update(prices)
        now = self.now_ms()
        liquidate = "Notstopp" if self.st["halted"] else "Notverkauf (Telegram)" if self.st.get("liquidate") else ""
        for symbol, pos in list(positions.items()):
            if pos.get("selftest"):
                self.close_position(symbol, "Funktionstest")
                continue
            if liquidate:                          # Notstopp/Notverkauf: so lange versuchen, bis alles verkauft ist
                self.close_position(symbol, liquidate)
                continue
            current = prices.get(symbol)
            if current is None:
                continue
            reason = strategy.exit_reason(pos["stop"], pos["target"], int(pos["deadline_ms"]), current, now)
            if reason:
                self.close_position(symbol, reason)
        if not positions and self.st.get("liquidate"):
            self.st["liquidate"] = False
            self.store.save()

    def close_position(self, symbol: str, reason: str) -> bool:
        pos = self.st["positions"].get(symbol)
        if not pos or self.st.get("pending"):
            return False
        market = self.broker.ensure_market(symbol)
        if market is None:
            self.alert(f"market-{symbol}", f"❗ {symbol}: Markt nicht gefunden – Verkauf unmöglich. Bitte von Hand prüfen.")
            return False
        self.refresh()
        mark = self.prices.get(symbol) or pos["entry_price"]
        # Eigene Reste früherer Trades mitverkaufen (Binance zieht die Kaufgebühr vom Coin ab, dadurch bleibt beim
        # Abrunden auf die Schrittweite jedes Mal ein kleiner Rest liegen). Nie mehr als das, was frei auf dem Konto liegt.
        ours = pos["amount"] + float(self.st["dust"].get(symbol, 0.0))
        amount = self.broker.round_amount(symbol, min(ours, self.balances.free(market.base)))
        if amount <= 0 or amount * mark < market.min_cost:
            self.book_out(symbol, pos, f"{reason} – Rest zu klein zum Verkaufen, bleibt auf dem Konto", mark)
            self.tg.send(f"ℹ️ {coin(symbol)} ({reason}): Die Position ist nur noch ca. {de(pos['amount'] * mark)} {self.q} "
                         f"wert – unter dem Binance-Minimum von {de(market.min_cost)} {self.q}, also nicht verkaufbar. "
                         f"Sie bleibt auf dem Konto und wird beim nächsten {coin(symbol)}-Verkauf mitverkauft.")
            return True
        client_id = self.client_id("s")
        self.st["pending"] = {"client_id": client_id, "symbol": symbol, "side": "sell", "reason": reason,
                              "created_ms": self.now_ms()}
        self.store.save()
        try:
            fill = self.broker.market_order(symbol, "sell", amount, client_id)
        except OrderUnclear as exc:
            self.alert("unclear", f"⚠️ {exc} Ich prüfe weiter, bevor ich neu handle.")
            return False
        except (OrderRejected, ExchangeProblem) as exc:
            self.st["pending"] = None
            self.store.save()
            self.alert(f"sell-{symbol}", f"❗ Verkauf {coin(symbol)} ({reason}) fehlgeschlagen: {exc}. "
                                         "Ich versuche es weiter.")
            return False
        self.book_sell(symbol, fill, reason)
        return True

    def book_sell(self, symbol: str, fill: Fill, reason: str) -> None:
        st = self.st
        pos = st["positions"][symbol]
        market = self.broker.ensure_market(symbol)
        dust_before = float(st["dust"].get(symbol, 0.0))
        sold = fill.amount
        remaining = pos["amount"] - min(sold, pos["amount"])
        partial = market is not None and remaining * fill.price >= market.min_cost
        cost_part = pos["cost"] * (sold / pos["amount"]) if partial and pos["amount"] > 0 else pos["cost"]
        proceeds = fill.cost - fill.fee_quote
        pnl = proceeds - cost_part
        st["realized_pnl"] = float(st.get("realized_pnl") or 0.0) + pnl
        st["fees_paid"] = float(st.get("fees_paid") or 0.0) + fill.fee_value
        if partial:
            pos["amount"] = remaining
            pos["cost"] -= cost_part
        else:
            del st["positions"][symbol]
            st["dust"][symbol] = max(0.0, pos["amount"] + dust_before - sold)   # Rest unter der Schrittweite
        trade = self._trade_record(symbol, pos, sold, cost_part, proceeds, fill.price, reason)
        st["closed"] = (st["closed"] + [trade])[-500:]
        st["pending"] = None
        self.refresh(after_trade=True)
        if pos.get("selftest"):
            st["selftest_done"] = True
        self.store.save()
        if pos.get("selftest"):
            self.tg.send(f"✅ Funktionstest bestanden: echte Order bei Binance – {qty(sold)} {coin(symbol)} gekauft und "
                         f"sofort wieder verkauft. Ergebnis (Gebühren und Kursdifferenz): {signed(pnl, 4)} {self.q}.\n"
                         "Schlüssel, Handelsrecht und Order-Weg funktionieren. Ab jetzt handelt die Regel.")
            return
        icon = "✅" if pnl >= 0 else "🔻"
        text = [f"{icon} VERKAUF {coin(symbol)} – {reason}",
                f"{qty(sold)} {coin(symbol)} zu {price_text(fill.price)} → {de(proceeds)} {self.q}",
                f"Ergebnis: {signed(pnl)} {self.q} ({pct(pnl / cost_part * 100 if cost_part else 0.0)})"]
        if partial:
            text.append(f"Teilverkauf – Rest {qty(remaining)} {coin(symbol)} bleibt offen.")
        text.append(f"Kapital jetzt: {de(self.equity)} {self.q}")
        self.tg.send("\n".join(text))

    def book_out(self, symbol: str, pos: dict[str, Any], reason: str, mark: float, sold_outside: bool = False) -> None:
        """
        Position ohne eigene Order ausbuchen.
        sold_outside=False: Rest unter dem Binance-Minimum. Er bleibt auf dem Konto, zählt erst als Erlös, wenn er beim
        nächsten Verkauf dieses Coins mitverkauft wird.
        sold_outside=True: Die Coins sind weg (von Hand verkauft oder abgehoben). Ihr Wert verlässt die Bot-Bücher wie eine
        Auszahlung. Wurden sie verkauft, hat refresh() den Erlös schon als Einzahlung gezählt – beides hebt sich auf.
        """
        st = self.st
        value = pos["amount"] * mark
        proceeds = value if sold_outside else 0.0
        trade = self._trade_record(symbol, pos, pos["amount"], pos["cost"], proceeds, mark, reason)
        st["closed"] = (st["closed"] + [trade])[-500:]
        st["realized_pnl"] = float(st.get("realized_pnl") or 0.0) + (proceeds - pos["cost"])
        st["positions"].pop(symbol, None)
        if sold_outside:
            st["dust"].pop(symbol, None)
            for key in ("peak_equity", "day_start_equity"):
                if st.get(key) is not None:
                    st[key] = max(0.0, float(st[key]) - value)
            st["net_deposits"] = float(st.get("net_deposits") or 0.0) - value
        else:
            st["dust"][symbol] = float(st["dust"].get(symbol, 0.0)) + pos["amount"]
        if pos.get("selftest"):
            self.st["selftest_done"] = True
        self.recompute_equity()
        self.store.save()

    def _trade_record(self, symbol: str, pos: dict[str, Any], amount: float, cost: float, proceeds: float,
                      exit_price: float, reason: str) -> dict[str, Any]:
        pnl = proceeds - cost
        return {
            "symbol": symbol, "opened_at": pos.get("opened_at"), "closed_at": self.iso(), "amount": amount,
            "entry_price": pos["entry_price"], "exit_price": exit_price, "cost": round(cost, 6),
            "proceeds": round(proceeds, 6), "pnl": round(pnl, 6), "pnl_pct": round(pnl / cost * 100, 3) if cost else 0.0,
            "r": round(pnl / pos["risk"], 3) if pos.get("risk") else None, "reason": reason,
            "selftest": bool(pos.get("selftest")),
        }

    # ------------------------------------------------------------------ Kaufen

    def check_entries(self) -> None:
        now = self.now_ms()
        tf = strategy.TIMEFRAME_MS
        candle_open = now // tf * tf           # Beginn der laufenden Kerze = Schluss der Signal-Kerze
        signal_ts = candle_open - tf
        if int(self.st["last_signal_candle"] or 0) >= signal_ts:
            return
        age = now - candle_open
        if age < SCAN_DELAY_MS:
            return
        if age > strategy.ENTRY_WINDOW_MS:
            log.info("Kaufzeitfenster der Kerze bis %s verpasst – nächste Prüfung %s.", self.when(candle_open),
                     self.when(candle_open + tf))
            self.st["last_signal_candle"] = signal_ts
            self.store.save()
            return
        if self.scan_state[0] != signal_ts:
            self.scan_state = (signal_ts, set(), [])
            self.scan_notes = {}
        _, done, checks = self.scan_state
        failed: list[str] = []
        for symbol in self.symbols:
            if symbol in done:
                continue
            try:
                candles = self.broker.fetch_candles(symbol, strategy.TIMEFRAME, strategy.FETCH_CANDLES)
            except ExchangeProblem as exc:
                log.warning("Kerzen %s: %s", symbol, exc)
                failed.append(symbol)
                continue
            closed = strategy.closed_candles(candles, now)
            if not closed or int(closed[-1][0]) != signal_ts:
                failed.append(symbol)            # Binance hat die Kerze noch nicht fertig
                continue
            check = strategy.evaluate(symbol, closed)
            if check.signal:                     # erst nach dem Kaufversuch als erledigt merken
                self.scan_notes[symbol] = self.try_enter(check)
            done.add(symbol)
            checks.append(check)
        if failed and age + LOOP_SECONDS * 1000 < strategy.ENTRY_WINDOW_MS:
            return                               # im nächsten Durchlauf erneut versuchen
        self.st["last_signal_candle"] = signal_ts
        self.store.save()
        self.report_scan(candle_open, checks, failed)

    def report_scan(self, candle_close: int, checks: list[strategy.Check], failed: list[str]) -> None:
        signals = [c for c in checks if c.signal]
        if not signals and not self.s.scan_reports:
            return
        lines = [f"🔎 4h-Prüfung {self.when(candle_close)}: {len(checks)} Coins geprüft."]
        for check in signals:
            lines.append(f"• Kaufsignal {coin(check.symbol)}: {self.scan_notes.get(check.symbol, '')}")
        if not signals:
            lines.append("Kein Kaufsignal.")
            near = sorted((c for c in checks if c.above_ema and c.gap_pct > 0), key=lambda c: c.gap_pct)[:3]
            if near:
                lines.append("Am nächsten dran: " + ", ".join(f"{coin(c.symbol)} (noch +{de(c.gap_pct, 1)} %)"
                                                              for c in near))
            below = sum(1 for c in checks if c.has_data and not c.above_ema)
            lines.append(f"{below} von {len(checks)} Coins unter der EMA 200 (Abwärtstrend, dort kauft die Regel nie).")
        if failed:
            lines.append(f"Nicht abrufbar: {', '.join(coin(s) for s in failed)}")
        lines.append(f"Nächste Prüfung: {self.when(candle_close + strategy.TIMEFRAME_MS)}")
        self.tg.send("\n".join(lines), silent=not signals)

    def try_enter(self, check: strategy.Check) -> str:
        st, s = self.st, self.s
        symbol = check.symbol
        if st["halted"]:
            return "nicht gekauft – Notstopp aktiv (/weiter)"
        if st["paused"]:
            return "nicht gekauft – pausiert (/weiter)"
        if st["day_limit_hit"]:
            return "nicht gekauft – Tageslimit erreicht"
        if symbol in st["positions"]:
            return "schon im Bestand"
        if st["entered"].get(symbol) == check.candle_ts:
            return "auf dieses Signal schon gekauft"
        if len(st["positions"]) >= s.max_positions:
            return f"nicht gekauft – schon {s.max_positions} Positionen offen"
        if st.get("pending"):
            return "nicht gekauft – vorherige Order wird noch geklärt"
        market = self.broker.ensure_market(symbol)
        self.refresh()
        current = self.broker.fetch_prices([symbol]).get(symbol) or check.close
        risk_money = self.equity * s.risk_per_trade_pct / 100
        budget = min(risk_money / check.stop_fraction, self.equity * s.max_position_pct / 100,
                     self.quote_free * CASH_BUFFER)
        minimum = max(market.min_cost, 5.0) * MIN_ORDER_BUFFER
        if budget < minimum:
            if self.quote_free * CASH_BUFFER >= minimum and minimum * check.stop_fraction <= self.equity * MAX_RISK_FRACTION:
                budget = minimum
            else:
                return f"nicht gekauft – zu wenig {self.q} frei ({de(self.quote_free)} {self.q})"
        amount = self.broker.round_amount(symbol, budget / current)
        if amount * current < minimum:
            amount = self.broker.round_amount(symbol, amount + market.amount_step)
        if amount <= 0 or amount < market.min_amount or amount * current > self.quote_free * CASH_BUFFER:
            return f"nicht gekauft – zu wenig {self.q} frei ({de(self.quote_free)} {self.q})"
        return self.execute_buy(symbol, amount, {"stop_fraction": check.stop_fraction,
                                                 "target_fraction": check.target_fraction,
                                                 "candle_ts": check.candle_ts, "atr": check.atr})

    def execute_buy(self, symbol: str, amount: float, info: dict[str, Any]) -> str:
        market = self.broker.ensure_market(symbol)
        client_id = self.client_id("b")
        self.st["pending"] = {"client_id": client_id, "symbol": symbol, "side": "buy", **info,
                              "base_before": self.balances.total(market.base) if self.balances else None,
                              "created_ms": self.now_ms()}
        self.store.save()
        try:
            fill = self.broker.market_order(symbol, "buy", amount, client_id)
        except OrderUnclear as exc:
            self.alert("unclear", f"⚠️ {exc} Ich prüfe weiter, bevor ich neu handle.")
            return "Ergebnis der Order unklar – wird geprüft"
        except (OrderRejected, ExchangeProblem) as exc:
            self.st["pending"] = None
            self.store.save()
            self.alert(f"buy-{symbol}", f"❗ Kauf {coin(symbol)} fehlgeschlagen: {exc}")
            return f"Kauf fehlgeschlagen ({exc})"
        self.book_buy(fill, self.st["pending"])
        return "gekauft ✅"

    def book_buy(self, fill: Fill, info: dict[str, Any]) -> None:
        st = self.st
        symbol = info["symbol"]
        market = self.broker.ensure_market(symbol)
        self.refresh(after_trade=True)
        net = fill.net_amount
        if info.get("base_before") is not None and market is not None:
            received = self.balances.total(market.base) - float(info["base_before"])
            if 0 < received <= fill.amount * 1.0001:
                net = received                   # das Konto ist die Wahrheit (Gebühr schon abgezogen)
        entry = fill.price
        cost = fill.cost + fill.fee_quote
        stop_fraction = float(info["stop_fraction"])
        candle = info.get("candle_ts")
        deadline = strategy.deadline_ms(int(candle)) if candle else self.now_ms() + 3_600_000
        position = {
            "symbol": symbol, "amount": net, "entry_price": entry, "cost": cost,
            "stop": entry * (1 - stop_fraction), "target": entry * (1 + float(info["target_fraction"])),
            "deadline_ms": deadline, "opened_at": self.iso(), "candle_ts": candle,
            "risk": cost * stop_fraction, "order_id": fill.order_id, "selftest": bool(info.get("selftest")),
        }
        st["positions"][symbol] = position
        if candle:
            st["entered"][symbol] = int(candle)
        st["fees_paid"] = float(st.get("fees_paid") or 0.0) + fill.fee_value
        st["pending"] = None
        self.prices[symbol] = entry
        self.recompute_equity()
        self.store.save()
        if position["selftest"]:
            return
        stop_pct = (position["stop"] / entry - 1) * 100
        target_pct = (position["target"] / entry - 1) * 100
        self.tg.send("\n".join([
            f"🟢 KAUF {coin(symbol)} (4h-Ausbruch)",
            f"{qty(net)} {coin(symbol)} zu {price_text(entry)} = {de(cost)} {self.q}",
            f"Stop {price_text(position['stop'])} ({pct(stop_pct)}) · Ziel {price_text(position['target'])} "
            f"({pct(target_pct)})",
            f"Spätestens verkaufen: {self.when(deadline)}",
            f"Risiko bis zum Stop: ca. {de(position['risk'])} {self.q} "
            f"({de(position['risk'] / max(self.equity, 1e-9) * 100, 1)} % des Kapitals)",
        ] + ([f"Gebühr: {fill.fee_note}"] if fill.fee_note else [])))

    def selftest(self) -> None:
        """Einmal beim ersten Echtgeld-Start: kleinstmöglicher Kauf und sofortiger Verkauf – beweist den Order-Weg."""
        candidates = [f"{c}/{self.q}" for c in SELFTEST_COINS] + self.symbols
        symbol = next((x for x in candidates if x in self.broker.markets and x not in self.st["positions"]), None)
        if symbol is None:
            return
        market = self.broker.markets[symbol]
        try:
            current = self.broker.fetch_prices([symbol])[symbol]
        except (ExchangeProblem, KeyError) as exc:
            self.tg.send(f"⚠️ Funktionstest verschoben: kein Kurs für {symbol} ({exc}).")
            return
        minimum = max(market.min_cost, 5.0) * 1.3
        if self.quote_free * CASH_BUFFER < minimum:
            self.tg.send(f"⚠️ Funktionstest übersprungen: nur {de(self.quote_free)} {self.q} frei (nötig: "
                         f"{de(minimum)} {self.q}). Ohne {self.q} kann der Bot nicht kaufen.")
            return
        amount = self.broker.round_amount(symbol, minimum / current)
        if amount * current < minimum:
            amount = self.broker.round_amount(symbol, amount + market.amount_step)
        self.tg.send(f"🧪 Funktionstest: Ich kaufe für ca. {de(amount * current)} {self.q} {coin(symbol)} und verkaufe "
                     "sofort wieder. Das beweist, dass echte Orders funktionieren (Kosten: wenige Cent).", silent=True)
        result = self.execute_buy(symbol, amount, {"stop_fraction": 0.5, "target_fraction": 10.0, "candle_ts": None,
                                                   "atr": 0.0, "selftest": True})
        if symbol not in self.st["positions"]:
            self.tg.send(f"❌ Funktionstest: Kauf nicht ausgeführt – {result}")
            return
        if not self.close_position(symbol, "Funktionstest"):
            self.tg.send("⚠️ Funktionstest: Kauf ok, Verkauf hat noch nicht geklappt – ich versuche es weiter.")

    # ------------------------------------------------------------------ Berichte

    def daily_report(self) -> None:
        now = self.local()
        today = now.date().isoformat()
        if now.hour < self.s.report_hour or self.st.get("last_report_day") == today:
            return
        self.st["last_report_day"] = today
        self.store.save()
        self.refresh()
        since = self.clock() - 86_400
        recent = [t for t in self.st["closed"]
                  if t.get("closed_at") and datetime.fromisoformat(t["closed_at"]).timestamp() >= since]
        lines = [f"☀️ Tagesbericht · {self.tag}", *self.summary_lines()]
        if recent:
            lines.append("Letzte 24 Stunden: " + "; ".join(f"{coin(t['symbol'])} {signed(t['pnl'])}" for t in recent))
        self.tg.send("\n".join(lines))

    def summary_lines(self) -> list[str]:
        st, s = self.st, self.s
        start = float(st["start_equity"] or 0.0)
        profit = self.equity - start - float(st.get("net_deposits") or 0.0)
        peak = float(st["peak_equity"] or self.equity)
        day_start = float(st["day_start_equity"] or self.equity)
        state = "läuft"
        if st["halted"]:
            state = f"🛑 Notstopp ({st['halt_reason']})"
        elif st["paused"]:
            state = "⏸ pausiert"
        elif st["day_limit_hit"]:
            state = "Tageslimit erreicht – heute keine Käufe"
        lines = [
            f"Zustand: {state}",
            f"Kapital: {de(self.equity)} {self.q} · seit Start {signed(profit)} {self.q}"
            + (f" ({pct(profit / start * 100)})" if start else ""),
            f"Frei: {de(self.quote_free)} {self.q} · Höchststand {de(peak)} {self.q}",
            f"Heute: {signed(self.equity - day_start)} {self.q} · Tageslimit −{de(s.daily_loss_limit_pct, 0)} %",
            f"Notstopp unter {de(peak * (1 - s.max_drawdown_pct / 100))} {self.q} (−{de(s.max_drawdown_pct, 0)} % "
            "vom Höchststand)",
        ]
        positions = st["positions"]
        lines.append(f"Positionen ({len(positions)}/{s.max_positions}):" if positions else "Keine offenen Positionen.")
        for symbol, pos in positions.items():
            mark = self.prices.get(symbol, pos["entry_price"])
            pnl = pos["amount"] * mark - pos["cost"]
            lines.append(f"• {coin(symbol)}: {qty(pos['amount'])} zu {price_text(pos['entry_price'])} → "
                         f"{price_text(mark)} ({pct((mark / pos['entry_price'] - 1) * 100)}, {signed(pnl)} {self.q})")
            lines.append(f"   Stop {price_text(pos['stop'])} · Ziel {price_text(pos['target'])} · bis "
                         f"{self.when(int(pos['deadline_ms']))}")
        trades = [t for t in st["closed"] if not t.get("selftest")]
        wins = sum(1 for t in trades if t["pnl"] > 0)
        lines.append(f"Abgeschlossen: {len(trades)} Trades ({wins} Gewinner) · {signed(sum(t['pnl'] for t in trades))} "
                     f"{self.q} · Gebühren bisher {de(float(st.get('fees_paid') or 0.0))} {self.q}")
        return lines

    # ------------------------------------------------------------------ Telegram-Befehle

    def handle(self, text: str) -> None:
        command = text.split()[0].lower().lstrip("/").split("@")[0] if text.split() else ""
        handlers: dict[str, Callable[[], None]] = {
            "status": self.cmd_status, "trades": self.cmd_trades, "markt": self.cmd_market,
            "pause": self.cmd_pause, "weiter": self.cmd_resume, "notverkauf": self.cmd_sell_all,
            "notverkauf_ja": self.cmd_sell_all_confirm, "hilfe": self.cmd_help, "help": self.cmd_help,
            "start": self.cmd_help,
        }
        handler = handlers.get(command)
        if handler is None:
            self.tg.send("Unbekannter Befehl. /hilfe zeigt alle Befehle.")
            return
        handler()

    def cmd_help(self) -> None:
        self.tg.send("\n".join([f"🤖 NewTry-Bot · {self.tag}"] + [f"/{c} – {d}" for c, d in COMMANDS] + [
            f"Gekauft wird nur direkt nach einem 4h-Kerzenschluss ({self.close_hours()} Uhr), wenn ein Coin über das "
            "Hoch der letzten 100 Kerzen ausbricht und über der EMA 200 liegt."]))

    def cmd_status(self) -> None:
        self.refresh()
        self.tg.send("\n".join([f"📊 Status · {self.tag}", *self.summary_lines(),
                                f"Nächste 4h-Prüfung: {self.when(self.next_close_ms())}"]))

    def cmd_trades(self) -> None:
        trades = self.st["closed"][-10:]
        if not trades:
            self.tg.send("Noch keine abgeschlossenen Trades.")
            return
        lines = ["📒 Letzte Trades:"]
        for t in reversed(trades):
            closed = self.local(int(datetime.fromisoformat(t["closed_at"]).timestamp() * 1000)).strftime("%d.%m. %H:%M")
            lines.append(f"• {closed} {coin(t['symbol'])}: {signed(t['pnl'])} {self.q} ({pct(t['pnl_pct'])}) – "
                         f"{t['reason']}")
        self.tg.send("\n".join(lines))

    def cmd_market(self) -> None:
        now = self.now_ms()
        checks: list[strategy.Check] = []
        for symbol in self.symbols:
            try:
                candles = self.broker.fetch_candles(symbol, strategy.TIMEFRAME, strategy.FETCH_CANDLES)
            except ExchangeProblem:
                continue
            checks.append(strategy.evaluate(symbol, strategy.closed_candles(candles, now)))
        above = sorted((c for c in checks if c.has_data and c.above_ema), key=lambda c: c.gap_pct)
        below = [c for c in checks if c.has_data and not c.above_ema]
        thin = [c for c in checks if not c.has_data]
        lines = ["📈 Marktlage (letzte geschlossene 4h-Kerze)",
                 f"Über der EMA 200 (Aufwärtstrend): {len(above)} von {len(checks)} Coins"]
        for check in above[:12]:
            if check.signal:
                lines.append(f"• {coin(check.symbol)}: KAUFSIGNAL auf der letzten Kerze")
            elif check.gap_pct <= 0:
                lines.append(f"• {coin(check.symbol)}: über dem Hoch, aber {check.reason}")
            else:
                lines.append(f"• {coin(check.symbol)}: noch +{de(check.gap_pct, 1)} % bis zum Ausbruch")
        if below:
            lines.append("Unter der EMA 200 (dort kauft die Regel nie): " + ", ".join(coin(c.symbol) for c in below))
        if thin:
            lines.append("Zu wenig Kursdaten (zu neu): " + ", ".join(coin(c.symbol) for c in thin))
        lines.append(f"Nächste Prüfung: {self.when(self.next_close_ms())}")
        self.tg.send("\n".join(lines))

    def cmd_pause(self) -> None:
        self.st["paused"] = True
        self.store.save()
        self.tg.send("⏸ Pausiert: keine neuen Käufe. Offene Positionen behalten Stop und Ziel. Wieder kaufen: /weiter")

    def cmd_resume(self) -> None:
        st = self.st
        was_halted = st["halted"]
        st["paused"] = False
        st["halted"] = False
        st["halt_reason"] = ""
        if was_halted:
            self.refresh()
            st["peak_equity"] = self.equity      # neuer Bezugspunkt, sonst löst der Notstopp sofort wieder aus
        self.store.save()
        self.tg.send("▶️ Weiter: Der Bot kauft wieder bei Signalen." + (
            f" Neuer Höchststand für den Notstopp: {de(self.equity)} {self.q}." if was_halted else ""))

    def cmd_sell_all(self) -> None:
        if not self.st["positions"]:
            self.tg.send("Keine offenen Positionen.")
            return
        self.confirm_until = self.clock() + 120
        self.tg.send(f"Wirklich alle {len(self.st['positions'])} Positionen sofort verkaufen und pausieren? "
                     "Dann innerhalb von 2 Minuten /notverkauf_ja senden.")

    def cmd_sell_all_confirm(self) -> None:
        if self.clock() > self.confirm_until:
            self.tg.send("Bitte zuerst /notverkauf senden.")
            return
        self.confirm_until = 0.0
        self.st["paused"] = True
        self.st["liquidate"] = True
        self.store.save()
        failed = [s for s in list(self.st["positions"]) if not self.close_position(s, "Notverkauf (Telegram)")]
        if not self.st["positions"]:
            self.st["liquidate"] = False
            self.store.save()
        self.tg.send("⏸ Notverkauf erledigt, Bot pausiert (/weiter)." if not failed else
                     f"⚠️ Noch nicht verkauft: {', '.join(coin(s) for s in failed)} – ich versuche es alle 10 Sekunden "
                     "weiter. Bot pausiert (/weiter).")


# ====================================================================== Startklar-Prüfung


def run_check(settings: Settings, broker: Broker, telegram: Telegram) -> int:
    ok = True
    q = settings.quote
    print(f"Modus: {'ECHTGELD (live)' if settings.live else 'PAPIER (Simulation mit echten Kursen)'}")
    try:
        symbols, missing = broker.load_markets(settings.coins)
    except (ExchangeProblem, AuthProblem) as exc:
        print(f"✘ Binance nicht erreichbar: {exc}")
        return 1
    print(f"✔ Binance erreichbar: {len(symbols)} Coins mit {q}-Markt"
          + (f" (ohne Markt, werden übersprungen: {', '.join(missing)})" if missing else ""))
    if not symbols:
        print(f"✘ Kein einziger Coin hat einen {q}-Markt – QUOTE in der .env prüfen.")
        return 1
    try:
        balances = broker.balances()
    except AuthProblem as exc:
        print(f"✘ Binance lehnt den API-Schlüssel ab: {exc}\n"
              "  → Binance-App → API-Verwaltung: Schlüssel aktiv? IP-Freigabe enthält die IP dieses Servers?")
        return 1
    except ExchangeProblem as exc:
        print(f"✘ Kontostand nicht abrufbar: {exc}")
        return 1
    free = balances.free(q)
    print(f"✔ Kontostand: {de(free)} {q} frei")
    others = {a: v for a, v in balances.nonzero().items() if a != q}
    if others:
        print("  Weitere Guthaben (der Bot rührt sie nicht an): " + ", ".join(f"{a} {qty(v)}" for a, v in others.items()))
    if free < 7:
        print(f"⚠ Weniger als 7 {q} frei: So kann der Bot nichts kaufen. In der Binance-App z. B. EUR in {q} tauschen.")
    if settings.live:
        permissions = broker.api_permissions()
        if permissions is not None:
            if permissions.get("enableSpotAndMarginTrading"):
                print("✔ Der API-Schlüssel darf Spot handeln.")
            else:
                print("✘ Der API-Schlüssel darf NICHT handeln → Binance-App → API-Verwaltung → Schlüssel bearbeiten → "
                      "„Spot- und Margin-Handel aktivieren“.")
                ok = False
            if permissions.get("enableWithdrawals"):
                print("⚠ Der Schlüssel darf AUSZAHLEN. Bitte in Binance abschalten – der Bot braucht das nie.")
            if not permissions.get("ipRestrict"):
                print("⚠ Der Schlüssel hat keine IP-Beschränkung. Empfohlen: nur die IP dieses Servers erlauben.")
    if telegram.enabled:
        sent = telegram.send("🧪 NewTry: Verbindungstest erfolgreich. Telegram funktioniert.")
        print("✔ Telegram: Testnachricht gesendet." if sent else "✘ Telegram: Senden fehlgeschlagen – "
              "TELEGRAM_BOT_TOKEN und TELEGRAM_CHAT_ID prüfen.")
        ok = ok and sent
    else:
        print("⚠ Telegram ist nicht eingerichtet – der Bot handelt trotzdem, meldet sich aber nicht.")
    print("STARTKLAR ✔" if ok else "NICHT STARTKLAR ✘")
    return 0 if ok else 1


# ====================================================================== Start


def build_broker(settings: Settings) -> Broker:
    if settings.live:
        client: Any = make_binance_client(settings.api_key, settings.api_secret)
    else:
        client = PaperExchange(settings.quote, settings.paper_start_balance, settings.data_dir / "paper_wallet.json")
    return Broker(client, settings.quote)


def setup_logging(data_dir: Path, level: int = logging.INFO) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    root.addHandler(stream)
    file_handler = logging.handlers.RotatingFileHandler(data_dir / "bot.log", maxBytes=2_000_000, backupCount=3,
                                                        encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    for noisy in ("ccxt", "urllib3", "requests"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="NewTry – Handelsbot für Binance Spot")
    parser.add_argument("--check", action="store_true", help="nur prüfen, ob alles startklar ist (handelt nicht)")
    parser.add_argument("--env", default=str(Path(__file__).resolve().parent / ".env"), help="Pfad zur .env")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.env)
    except ConfigError as exc:
        print(f"KONFIGURATIONSFEHLER in {args.env}:\n{exc}", file=sys.stderr)
        return 2
    setup_logging(settings.data_dir, logging.WARNING if args.check else logging.INFO)
    broker = build_broker(settings)
    telegram = Telegram(settings.telegram_token, settings.telegram_chat_id)
    if args.check:
        return run_check(settings, broker, telegram)

    # Getrennte Gedächtnisse für Papier und Echtgeld: Simulierte Positionen landen nie im echten Konto.
    bot = Bot(settings, broker, telegram, StateStore(settings.data_dir / f"state-{settings.mode}.json"))

    def stop(signum: int, _frame: Any) -> None:
        log.info("Signal %s – fahre geordnet herunter.", signum)
        bot.running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        bot.startup()
    except ConfigError as exc:
        log.error("%s", exc)
        telegram.send(f"❗ NewTry startet nicht: {exc}")
        return 2
    except AuthProblem as exc:
        log.error("%s", exc)
        telegram.send(f"❗ NewTry startet nicht: Binance lehnt den API-Schlüssel ab ({exc}). Prüfe in der Binance-App: "
                      "Schlüssel aktiv, Spot-Handel erlaubt, IP-Freigabe für den Server.")
        return 2
    except ExchangeProblem as exc:
        log.error("Start fehlgeschlagen (Binance nicht erreichbar): %s – Neustart in 30 Sekunden.", exc)
        return 1
    log.info("Bot läuft (%s).", settings.mode)
    bot.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
