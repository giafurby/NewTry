"""
Live-Wächter aus der Forschungsrunde v2 (lab/ERGEBNISSE_V2.md). Sie ändern keine Handelsregel. Sie prüfen, ob die
Wirklichkeit noch zu der Simulation passt, auf der die Regeln beruhen (Idee aus azubiassist: Vorwärtstest und Live-Schatten,
aber ohne Hürden, die das Handeln selbst blockieren).

1. AUSFÜHRUNGSWÄCHTER  Jeder Kauf wird mit dem Schlusskurs der Signal-Kerze verglichen. Die Simulation kauft eine Minute
   nach dem Schluss; dabei lag der Kaufkurs im Mittel ENTRY_DRIFT_PCT über dem Schluss. Kauft der Bot beim Crash-Kauf über
   die letzten `window` Käufe im Schnitt um mehr als `limit` Prozentpunkte schlechter, ist der Vorteil dieser Regel
   aufgezehrt (Gewinnschwelle: ~0,67 % Kosten je Seite, 2025/26 deutlich weniger). Dann setzt der Bot NUR den Crash-Kauf
   aus und meldet es. Weiter mit /weiter.
2. VORWÄRTSTEST  Durchschnitt der letzten 30 echten Trades je Regel gegen die Rückblick-Verteilung: Liegt er unter dem
   5-%-Quantil von 30 aufeinanderfolgenden Trades 2018–2026, passt der Markt womöglich nicht mehr zur Regel. Nur Meldung –
   bei so wenigen Trades entscheidet ein Mensch, nicht eine Statistik.
3. SCHLÜSSEL-HYGIENE (täglich, nur Echtgeld)  Der API-Schlüssel darf handeln, aber nie auszahlen.

Alles hier ist reine Rechnung ohne Börse und ohne Telegram (testbar). Der Bot ruft es an den passenden Stellen auf.
"""
from __future__ import annotations

from typing import Any, Optional

# Referenzwerte aus lab/live_reference.py (Kosten 0,20 % je Seite, Kauf 1 Minute nach Kerzenschluss, 2018–10/2026)
REFERENCE: dict[str, dict[str, float]] = {
    "trend": {"entry_drift_pct": 0.066, "median_30_pct": 2.84, "p05_30_pct": -1.69, "trades": 588},
    "dip": {"entry_drift_pct": 0.154, "median_30_pct": 1.06, "p05_30_pct": -0.89, "trades": 836},
}
FORWARD_WINDOW = 30
KEEP_SLIPPAGE = 50
LABEL = {"trend": "Trend", "dip": "Crash-Kauf"}
# Verkäufe, die nichts über die Regel aussagen (Notstopp, Handverkauf, Funktionstest …)
NOT_RULE_EXITS = ("Notstopp", "Notverkauf", "außerhalb des Bots", "Funktionstest", "Rest unter")


def _pct(value: float) -> str:
    """+1,23 % / −0,89 % (wie bot.pct: deutsches Komma, echtes Minuszeichen)."""
    return ("+" if value >= 0 else "−") + f"{abs(value):.2f}".replace(".", ",") + " %"


def _num(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def record_entry(state: dict[str, Any], kind: str, signal_price: float, fill_price: float) -> Optional[float]:
    """Kauf-Abweichung in % vom Signal-Schluss speichern (positiv = teurer gekauft). Rückgabe: Abweichung."""
    if not signal_price or signal_price <= 0 or not fill_price or fill_price <= 0:
        return None
    slip = (fill_price / signal_price - 1.0) * 100.0
    book = state.setdefault("slippage", {})
    book[kind] = (list(book.get(kind) or []) + [round(slip, 4)])[-KEEP_SLIPPAGE:]
    return slip


def excess_slippage(state: dict[str, Any], kind: str, window: int) -> Optional[tuple[float, float]]:
    """(Ø Abweichung der letzten `window` Käufe, davon über der Simulation) oder None bei zu wenigen Käufen."""
    values = list((state.get("slippage") or {}).get(kind) or [])
    if window <= 0 or len(values) < window:
        return None
    mean = sum(values[-window:]) / window
    return mean, mean - REFERENCE[kind]["entry_drift_pct"]


def dip_execution_verdict(state: dict[str, Any], limit_pct: float, window: int) -> Optional[str]:
    """Begründung, wenn der Crash-Kauf ausgesetzt werden soll, sonst None. limit_pct <= 0: Wächter aus."""
    if limit_pct <= 0:
        return None
    result = excess_slippage(state, "dip", window)
    if result is None:
        return None
    mean, excess = result
    if excess <= limit_pct:
        return None
    return (f"die letzten {window} Crash-Käufe lagen im Schnitt {_pct(mean)} über dem Signal-Schluss, "
            f"{_num(excess)} Prozentpunkte schlechter als in der Simulation (Grenze {_num(limit_pct)})")


def rule_trades(closed: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [t for t in closed if t.get("kind", "trend") == kind and not t.get("selftest")
            and not any(word in str(t.get("reason", "")) for word in NOT_RULE_EXITS)]


def forward_status(closed: list[dict[str, Any]], kind: str) -> Optional[dict[str, Any]]:
    trades = rule_trades(closed, kind)
    if not trades:
        return None
    last = trades[-FORWARD_WINDOW:]
    mean = sum(float(t.get("pnl_pct") or 0.0) for t in last) / len(last)
    ref = REFERENCE[kind]
    return {"kind": kind, "trades": len(trades), "window": len(last), "mean_pct": mean,
            "median_ref_pct": ref["median_30_pct"], "p05_ref_pct": ref["p05_30_pct"],
            "warning": len(last) >= FORWARD_WINDOW and mean < ref["p05_30_pct"]}


def forward_line(status: dict[str, Any]) -> str:
    text = (f"Vorwärtstest {LABEL[status['kind']]}: {status['trades']} Trades, Ø der letzten {status['window']} "
            f"{_pct(status['mean_pct'])} (Rückblick: Median {_pct(status['median_ref_pct'])}, "
            f"Warnschwelle {_pct(status['p05_ref_pct'])})")
    if status["window"] < FORWARD_WINDOW:
        text += f" – Urteil ab {FORWARD_WINDOW} Trades"
    elif status["warning"]:
        text += " ⚠️"
    return text


def forward_alert(state: dict[str, Any], kind: str) -> Optional[str]:
    """Meldung, wenn der Vorwärtstest dieser Regel gerade in den Warnbereich gerutscht ist (einmal je Abrutschen)."""
    status = forward_status(state.get("closed") or [], kind)
    flags = state.setdefault("forward_warned", {})
    if status is None or not status["warning"]:
        if status is not None:
            flags[kind] = False
        return None
    if flags.get(kind):
        return None
    flags[kind] = True
    return ("⚠️ Vorwärtstest " + LABEL[kind] + f": Die letzten {FORWARD_WINDOW} Trades brachten im Schnitt "
            f"{_pct(status['mean_pct'])} je Trade. Im Rückblick 2018–2026 war das in weniger als 5 % aller Phasen so "
            f"schlecht (Median {_pct(status['median_ref_pct'])}). Möglich: Pech oder ein Markt, in dem die Regel nicht "
            "mehr trägt. Der Bot handelt weiter; mit /pause kannst du neue Käufe anhalten.")


def key_problems(permissions: Optional[dict[str, Any]]) -> list[str]:
    """Probleme des API-Schlüssels (leere Liste = in Ordnung, None-Eingabe = nicht prüfbar)."""
    if permissions is None:
        return []
    problems = []
    if permissions.get("enableWithdrawals"):
        problems.append("Der API-Schlüssel darf AUSZAHLEN. Bitte in der Binance-App abschalten – der Bot braucht das nie.")
    if not permissions.get("enableSpotAndMarginTrading", True):
        problems.append("Der API-Schlüssel darf nicht mehr handeln (Spot-Handel ausgeschaltet).")
    return problems
