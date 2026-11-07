"""
Zwei Handelsregeln, die sich ergänzen (Auswertung: research/ERGEBNISSE.md):

1. TREND – 4-Stunden-Ausbruch (unten, `evaluate`).
2. CRASH-KAUF – nach einem schnellen Einbruch kaufen, nach 4 Stunden wieder verkaufen (`evaluate_dip`).

Regel 1 im Detail – 4-Stunden-Trendausbruch.

Sie stammt aus der Echtdaten-Studie des alten Projekts (azubiassist, ANLEITUNG_HETZNER.md Teil 18 und 20), geprüft auf
echten Binance-Kerzen von 2017 bis 10/2026 auf 10 Coins. Der Rückblick war positiv, die Zukunft wird schwächer sein:

  KAUF   wenn eine 4h-Kerze ÜBER dem Hoch der vorherigen 100 Kerzen schließt UND über der EMA 200 liegt.
  STOP   2 × ATR(14) unter dem Einstieg (mindestens 0,2 %; liegt er weiter als 10 % weg, wird ausgelassen).
  ZIEL   15 × ATR(14) über dem Einstieg.
  ZEIT   nach spätestens 120 Kerzen (20 Tage) wird verkauft.
  Kein Trailing-Stop. Nur etwa jeder vierte Trade gewinnt, die Gewinner sind dafür groß.

Alles hier ist reine Rechnung ohne Börse, damit es sich prüfen und testen lässt.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

TIMEFRAME = "4h"
TIMEFRAME_MS = 4 * 60 * 60 * 1000
BREAKOUT_BARS = 100
EMA_BARS = 200
ATR_BARS = 14
STOP_ATR = 2.0
TARGET_ATR = 15.0
MAX_HOLD_BARS = 120
MIN_STOP_FRACTION = 0.002
MAX_STOP_FRACTION = 0.10
MIN_REWARD_RISK = 1.5
FETCH_CANDLES = 1000                      # Vorlauf, damit die EMA 200 eingeschwungen ist
ENTRY_WINDOW_MS = max(15 * 60 * 1000, TIMEFRAME_MS // 10)   # gekauft wird nur kurz nach dem Kerzenschluss

# Eine Kerze: (Startzeit in ms, open, high, low, close, volume)
Candle = Sequence[float]


def ema(values: Sequence[float], span: int) -> list[Optional[float]]:
    """Exponentieller Durchschnitt wie pandas ewm(span, adjust=False, min_periods=span)."""
    alpha = 2.0 / (span + 1.0)
    out: list[Optional[float]] = []
    current: Optional[float] = None
    for index, value in enumerate(values):
        current = value if current is None else alpha * value + (1.0 - alpha) * current
        out.append(current if index >= span - 1 else None)
    return out


def wilder_atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
               period: int = ATR_BARS) -> list[Optional[float]]:
    """Average True Range mit Wilder-Glättung (Startwert = Mittel der ersten `period` True Ranges)."""
    true_ranges: list[float] = []
    for index in range(len(closes)):
        if index == 0:
            true_ranges.append(highs[0] - lows[0])
            continue
        previous = closes[index - 1]
        true_ranges.append(max(highs[index] - lows[index], abs(highs[index] - previous), abs(lows[index] - previous)))
    out: list[Optional[float]] = [None] * len(true_ranges)
    if len(true_ranges) < period:
        return out
    average = sum(true_ranges[:period]) / period
    out[period - 1] = average
    for index in range(period, len(true_ranges)):
        average = (average * (period - 1) + true_ranges[index]) / period
        out[index] = average
    return out


@dataclass(frozen=True)
class Check:
    """Ergebnis der Prüfung der letzten geschlossenen Kerze eines Coins."""
    symbol: str
    candle_ts: int
    close: float
    prior_high: float
    ema200: float
    atr: float
    signal: bool
    reason: str
    stop_fraction: float = 0.0
    target_fraction: float = 0.0

    @property
    def gap_pct(self) -> float:
        """So viel % muss der Kurs noch steigen, bis er über dem 100-Kerzen-Hoch schließt (negativ = darüber)."""
        return (self.prior_high / self.close - 1.0) * 100.0 if self.close > 0 else float("inf")

    @property
    def above_ema(self) -> bool:
        return self.close >= self.ema200

    @property
    def has_data(self) -> bool:
        return self.ema200 != float("inf")


def closed_candles(candles: Sequence[Candle], now_ms: int) -> list[Candle]:
    """Nur abgeschlossene Kerzen (die laufende Kerze liefert Binance immer als letzte mit)."""
    return [c for c in candles if int(c[0]) + TIMEFRAME_MS <= now_ms]


def evaluate(symbol: str, candles: Sequence[Candle]) -> Check:
    """Prüft die LETZTE Kerze der Liste (aufsteigend sortiert, nur geschlossene Kerzen)."""
    if len(candles) < EMA_BARS + 1:
        last = candles[-1] if candles else (0, 0, 0, 0, 0, 0)
        return Check(symbol, int(last[0]), float(last[4]), float("inf"), float("inf"), 0.0, False,
                     f"zu wenig Kursdaten ({len(candles)} Kerzen)")
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]
    closes = [float(c[4]) for c in candles]
    ema200 = ema(closes, EMA_BARS)[-1]
    atr = wilder_atr(highs, lows, closes, ATR_BARS)[-1]
    last = candles[-1]
    close = closes[-1]
    prior_high = max(highs[-1 - BREAKOUT_BARS:-1])
    base = dict(symbol=symbol, candle_ts=int(last[0]), close=close, prior_high=prior_high,
                ema200=float(ema200), atr=float(atr or 0.0))
    if close <= prior_high:
        return Check(**base, signal=False, reason="kein Ausbruch")
    if close < float(ema200):
        return Check(**base, signal=False, reason="Ausbruch, aber unter der EMA 200")
    if not atr or atr <= 0 or close <= 0:
        return Check(**base, signal=False, reason="ATR ungültig")
    atr_fraction = float(atr) / close
    stop_fraction = max(STOP_ATR * atr_fraction, MIN_STOP_FRACTION)
    if stop_fraction > MAX_STOP_FRACTION:
        return Check(**base, signal=False, reason=f"zu schwankungsreich (Stop {stop_fraction * 100:.1f} % entfernt)")
    target_fraction = max(TARGET_ATR * atr_fraction, stop_fraction * MIN_REWARD_RISK)
    return Check(**base, signal=True, reason="Kaufsignal", stop_fraction=stop_fraction, target_fraction=target_fraction)


def deadline_ms(signal_candle_ts: int) -> int:
    """Zeit-Stop: Ende der 120. Kerze ab der Einstiegs-Kerze (die Kerze nach dem Signal)."""
    return int(signal_candle_ts) + TIMEFRAME_MS + MAX_HOLD_BARS * TIMEFRAME_MS


def exit_reason(stop: float, target: Optional[float], deadline: int, price: float, now_ms: int,
                time_label: str = "Zeit-Stop (20 Tage)") -> Optional[str]:
    if price <= stop:
        return "Stop"
    if target is not None and price >= target:
        return "Ziel"
    if now_ms >= deadline:
        return time_label
    return None


# ====================================================================== Regel 2: Crash-Kauf
#
# KAUF   wenn eine 15-Minuten-Kerze mindestens 10 % unter dem Schluss von vor 4 Stunden (16 Kerzen) schließt.
#        Das sind meist Zwangsliquidationen, nach denen der Kurs oft ein Stück zurückfedert.
# GRÖSSE 20 % des Kapitals, höchstens 5 solcher Positionen, nur große, geprüfte Coins.
# RAUS   nach 4 Stunden – oder beim Notstop 15 % unter dem Einstieg.
# SPERRE nach einem Notstop 24 Stunden kein neuer Crash-Kauf in diesem Coin: Ohne diese Sperre würde die Regel einen
#        Coin, der wie LUNA 2022 auf null fällt, immer wieder nachkaufen (Simulation: 52 Käufe statt 4).

DIP_TIMEFRAME = "15m"
DIP_TIMEFRAME_MS = 15 * 60 * 1000
DIP_LOOKBACK_BARS = 16
DIP_FETCH_CANDLES = 40
DIP_ENTRY_WINDOW_MS = 5 * 60 * 1000       # nur direkt nach dem Kerzenschluss kaufen, sonst ist die Chance vorbei


@dataclass(frozen=True)
class DipCheck:
    symbol: str
    candle_ts: int
    close: float
    reference: float
    change_pct: float
    signal: bool


def evaluate_dip(symbol: str, candles: Sequence[Candle], drop_pct: float) -> DipCheck:
    """Prüft die LETZTE geschlossene 15m-Kerze: Schluss mindestens `drop_pct` % unter dem Schluss 16 Kerzen davor?
    Fehlt in diesem Fenster eine Kerze (Börsenwartung), gibt es kein Signal – das wäre kein echter Einbruch."""
    need = DIP_LOOKBACK_BARS + 1
    if len(candles) < need:
        last = candles[-1] if candles else (0, 0, 0, 0, 0, 0)
        return DipCheck(symbol, int(last[0]), float(last[4]), 0.0, 0.0, False)
    window = candles[-need:]
    contiguous = all(int(window[k + 1][0]) - int(window[k][0]) == DIP_TIMEFRAME_MS for k in range(len(window) - 1))
    close, reference = float(window[-1][4]), float(window[0][4])
    change = (close / reference - 1.0) * 100.0 if reference > 0 else 0.0
    return DipCheck(symbol, int(window[-1][0]), close, reference, change, contiguous and change <= -abs(drop_pct))
