"""
Datenschicht des Forschungslabors: alle Coins auf EINER 15-Minuten-Zeitachse, dazu die Ausführungspreise.

Ausführungspreis (`EP`): Eine Entscheidung fällt auf dem Schluss der Kerze i. Gehandelt wird in Kerze i+1 – nicht zum
Eröffnungskurs (das wäre die Sekunde des Kerzenschlusses, die kein Bot erreicht), sondern zum Eröffnungskurs der
ZWEITEN Minute (rund 60 Sekunden später, aus den 1-Minuten-Daten). Fehlt die Minute, gilt der Eröffnungskurs der Kerze.
Damit fallen Fehlprints in der ersten Minute (z. B. ETH 22.08.2017: 144 statt 300 USDT) heraus.

Höhere Zeitebenen (1h, 4h, 1d) werden aus den 15m-Kerzen gebaut, mit UTC-Grenzen wie bei Binance. Eine Kerze gilt nur,
wenn ihre letzte 15m-Kerze vorhanden ist (sonst wäre der „Schluss“ nicht der echte Schluss).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "TRXUSDT", "DOGEUSDT", "ZECUSDT", "ADAUSDT", "BCHUSDT")
STEP = 900_000
DAY = 86_400_000


@dataclass
class Market:
    T: np.ndarray          # (N,) Startzeit der 15m-Kerze in ms
    O: np.ndarray          # (N, K) NaN = keine Kerze
    H: np.ndarray
    L: np.ndarray
    C: np.ndarray
    CF: np.ndarray         # Schluss, vorwärts aufgefüllt (zur Bewertung offener Positionen)
    V: np.ndarray          # Volumen (Basis-Währung)
    live: np.ndarray       # (N, K) bool: Kerze vorhanden
    EP: np.ndarray         # (N, K) Ausführungspreis in Kerze i (Open der 2. Minute, sonst Open)
    symbols: tuple

    @property
    def N(self) -> int:
        return len(self.T)

    @property
    def K(self) -> int:
        return len(self.symbols)

    def index_of(self, when: str) -> int:
        return int(np.searchsorted(self.T, int(pd.Timestamp(when, tz="UTC").timestamp() * 1000)))


def _ffill(a: np.ndarray) -> np.ndarray:
    out = a.copy()
    for j in range(a.shape[1]):
        col = a[:, j]
        valid = np.isfinite(col)
        idx = np.where(valid, np.arange(len(col)), 0)
        np.maximum.accumulate(idx, out=idx)
        filled = col[idx]
        filled[: int(np.argmax(valid))] = np.nan
        out[:, j] = filled
    return out


def load_market(cache15: Path | str, cache1m: Path | str | None = None, symbols=SYMBOLS) -> Market:
    cache15 = Path(cache15)
    raw = {s: np.load(cache15 / f"{s}_15m.npz") for s in symbols}
    t0 = min(int(d["t"][0]) for d in raw.values())
    t1 = max(int(d["t"][-1]) for d in raw.values())
    T = np.arange(t0, t1 + STEP, STEP, dtype=np.int64)
    N, K = len(T), len(symbols)
    O, H, L, C, V = (np.full((N, K), np.nan) for _ in range(5))
    for j, s in enumerate(symbols):
        d = raw[s]
        pos = ((d["t"] - t0) // STEP).astype(np.int64)
        O[pos, j], H[pos, j], L[pos, j], C[pos, j], V[pos, j] = d["o"], d["h"], d["l"], d["c"], d["v"]
    live = np.isfinite(O)
    EP = O.copy()
    if cache1m is not None:
        cache1m = Path(cache1m)
        for j, s in enumerate(symbols):
            folder = cache1m / s
            if not folder.exists():
                continue
            t_m = np.load(folder / "t.npy", mmap_mode="r")
            o_m = np.load(folder / "o.npy", mmap_mode="r")
            want = T + 60_000
            k = np.searchsorted(t_m, want)
            k = np.minimum(k, len(t_m) - 1)
            hit = (np.asarray(t_m[k]) == want) & live[:, j]
            EP[hit, j] = np.asarray(o_m[k[hit]])
    return Market(T=T, O=O, H=H, L=L, C=C, CF=_ffill(C), V=V, live=live, EP=EP, symbols=tuple(symbols))


@dataclass
class Bars:
    """Höhere Zeitebene je Coin. end[b, j] = 15m-Index der letzten Kerze (= Entscheidungszeitpunkt), -1 = unvollständig."""
    minutes: int
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    end: np.ndarray        # (B, K) int64
    t: np.ndarray          # (B,) Startzeit der Kerze


def aggregate(m: Market, minutes: int) -> Bars:
    block_ms = minutes * 60_000
    bid = m.T // block_ms
    ub, first = np.unique(bid, return_index=True)
    B, K = len(ub), m.K
    o, h, l, c, v = (np.full((B, K), np.nan) for _ in range(5))
    end = np.full((B, K), -1, dtype=np.int64)
    bpos = np.searchsorted(ub, bid)
    for j in range(K):
        lv = m.live[:, j]
        df = pd.DataFrame({"b": bpos[lv], "i": np.flatnonzero(lv), "o": m.O[lv, j], "h": m.H[lv, j], "l": m.L[lv, j],
                           "c": m.C[lv, j], "v": m.V[lv, j]})
        g = df.groupby("b", sort=True)
        idx = g["b"].first().to_numpy()
        o[idx, j] = g["o"].first().to_numpy()
        h[idx, j] = g["h"].max().to_numpy()
        l[idx, j] = g["l"].min().to_numpy()
        c[idx, j] = g["c"].last().to_numpy()
        v[idx, j] = g["v"].sum().to_numpy()
        last_i = g["i"].last().to_numpy()
        complete = (m.T[last_i] + STEP) % block_ms == 0
        end[idx[complete], j] = last_i[complete]
        # unvollständige Kerzen: Kennzahlen bleiben (für gleitende Werte), aber kein Signal (end = -1)
    return Bars(minutes=minutes, o=o, h=h, l=l, c=c, v=v, end=end, t=ub * block_ms)


def to_grid(m: Market, bars: Bars, values: np.ndarray, fill=False) -> np.ndarray:
    """Werte einer höheren Zeitebene (B, K) auf die 15m-Achse legen: gültig ab dem Schluss der Kerze."""
    out = np.full((m.N, m.K), fill if values.dtype == bool else np.nan, dtype=values.dtype)
    for j in range(m.K):
        ok = bars.end[:, j] >= 0
        out[bars.end[ok, j], j] = values[ok, j]
    return out
