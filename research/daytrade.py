"""
Teil 1: Daytrading-Screening auf 15m und 1h (alle 10 Coins, gepoolt).
Einstieg zum Open der Folgekerze, Ausstieg nach N Kerzen zum Close (fester Horizont) – ODER früher bei Stop (1,5 ATR).
Kosten je Seite: 0,10 % Gebühr + 0,05 % Schlupf/Spread = 0,15 % (Hin und zurück 0,30 %).
Auswahl NUR auf In-Sample (bis 31.12.2022), Bewertung Out-of-Sample (ab 01.01.2023).
Aufruf: python -I daytrade.py <cache>
"""
import itertools
import sys
from pathlib import Path

import numpy as np

C = Path(sys.argv[1])
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "TRXUSDT", "DOGEUSDT", "ZECUSDT", "ADAUSDT", "BCHUSDT"]
SPLIT = 1672531200000  # 2023-01-01 UTC
COST = 0.0015


def ema(x, n):
    a = 2 / (n + 1)
    out = np.empty_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    out[: n - 1] = np.nan
    return out


def rsi(c, n):
    d = np.diff(c, prepend=c[0])
    up, dn = np.clip(d, 0, None), np.clip(-d, 0, None)
    au, ad = np.empty_like(c), np.empty_like(c)
    au[:n], ad[:n] = np.nan, np.nan
    au[n], ad[n] = up[1:n + 1].mean(), dn[1:n + 1].mean()
    for i in range(n + 1, len(c)):
        au[i] = (au[i - 1] * (n - 1) + up[i]) / n
        ad[i] = (ad[i - 1] * (n - 1) + dn[i]) / n
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = au / ad
    return 100 - 100 / (1 + rs)


def rolling(x, n, fn):
    from numpy.lib.stride_tricks import sliding_window_view
    out = np.full(len(x), np.nan)
    out[n - 1:] = fn(sliding_window_view(x, n), axis=1)
    return out


def atr(h, l, c, n=14):
    pc = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    out = np.full(len(c), np.nan)
    out[n - 1] = tr[:n].mean()
    for i in range(n, len(c)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def load(sym, tf):
    d = np.load(C / f"{sym}_{tf}.npz")
    t, o, h, l, c, v = (d[k] for k in "tohlcv")
    f = {"t": t, "o": o, "h": h, "l": l, "c": c}
    f["ema200"] = ema(c, 200)
    f["rsi2"], f["rsi14"] = rsi(c, 2), rsi(c, 14)
    mid, sd = rolling(c, 20, np.mean), rolling(c, 20, np.std)
    f["bbz"] = (c - mid) / sd
    f["atr"] = atr(h, l, c)
    for n in (20, 48, 96):
        hh = rolling(h, n, np.max)
        f[f"prior_high{n}"] = np.concatenate(([np.nan], hh[:-1]))
    vm, vs = rolling(v, 20, np.mean), rolling(v, 20, np.std)
    f["volz"] = np.concatenate(([np.nan], ((v - np.concatenate(([np.nan], vm[:-1]))) / np.concatenate(([np.nan], vs[:-1])))[1:]))
    for m in (4, 16):
        f[f"ret{m}"] = c / np.concatenate((np.full(m, np.nan), c[:-m])) - 1
    return f


def trades(f, mask, horizon, stop_atr):
    """Netto-Rendite je Signal: Einstieg Open i+1, Ausstieg Close i+horizon oder Stop (Kurs = Stop bzw. Open bei Lücke)."""
    n = len(f["c"])
    idx = np.flatnonzero(mask[: n - horizon - 1])
    if idx.size == 0:
        return idx, np.array([])
    entry = f["o"][idx + 1]
    exit_price = f["c"][idx + horizon].copy()
    if stop_atr:
        stop = entry - stop_atr * f["atr"][idx]
        alive = np.ones(idx.size, bool)
        for k in range(1, horizon + 1):
            lo, op = f["l"][idx + k], f["o"][idx + k]
            hit = alive & (lo <= stop)
            exit_price[hit] = np.minimum(stop[hit], op[hit])
            alive &= ~hit
    gross = exit_price / entry
    net = gross * (1 - COST) ** 2 - 1
    return idx, net


FAMILIES = {
    "RSI2<th": [("rsi2", th) for th in (5, 10)],
    "RSI14<th": [("rsi14", th) for th in (20, 25, 30)],
    "BB-z<-k": [("bbz", k) for k in (2.0, 2.5, 3.0)],
    "Ausbruch N": [(n, z) for n in (20, 48, 96) for z in (0.0, 1.5)],
    "Einbruch X%/M": [(m, x) for m in (4, 16) for x in (0.02, 0.03, 0.05)],
}


def signal(f, family, p, trend):
    c = f["c"]
    with np.errstate(invalid="ignore"):
        if family.startswith("RSI"):
            m = f[p[0]] < p[1]
        elif family.startswith("BB"):
            m = f["bbz"] < -p[1]
        elif family.startswith("Ausbruch"):
            m = (c > f[f"prior_high{p[0]}"]) & (f["volz"] > p[1])
        else:
            m = f[f"ret{p[0]}"] < -p[1]
        if trend:
            m &= c > f["ema200"]
    return m & np.isfinite(f["atr"])


results = []
for tf in ("15m", "1h"):
    frames = {s: load(s, tf) for s in SYMBOLS}
    for family, params in FAMILIES.items():
        for p, trend, horizon, stop in itertools.product(params, (False, True), (4, 8, 16, 32), (0, 1.5)):
            nets_is, nets_oos = [], []
            for f in frames.values():
                idx, net = trades(f, signal(f, family, p, trend), horizon, stop)
                is_mask = f["t"][idx] < SPLIT
                nets_is.append(net[is_mask])
                nets_oos.append(net[~is_mask])
            a, b = np.concatenate(nets_is), np.concatenate(nets_oos)
            results.append((tf, family, p, trend, horizon, stop, a.size, a.mean() if a.size else np.nan,
                            (a > 0).mean() if a.size else np.nan, b.size, b.mean() if b.size else np.nan))
    # Vergleich: in jeder Kerze kaufen (= Markttrend + Kosten)
    for horizon in (4, 8, 16, 32):
        a, b = [], []
        for f in frames.values():
            idx, net = trades(f, np.isfinite(f["atr"]), horizon, 0)
            a.append(net[f["t"][idx] < SPLIT]); b.append(net[f["t"][idx] >= SPLIT])
        a, b = np.concatenate(a), np.concatenate(b)
        print(f"{tf} IMMER KAUFEN, {horizon:>2} Kerzen halten: IS netto {a.mean()*100:+.3f} %  OOS netto {b.mean()*100:+.3f} %  "
              f"(brutto IS {(a.mean()+0.003)*100:+.3f} %)")

valid = [r for r in results if r[6] >= 300]
print(f"\nGetestete Varianten: {len(results)}  (davon mit ≥300 IS-Signalen: {len(valid)})")
print(f"Varianten mit positivem IS-Netto: {sum(1 for r in valid if r[7] > 0)}")
print(f"Varianten mit positivem OOS-Netto (alle): {sum(1 for r in results if r[9] >= 100 and r[10] > 0)}")
print("\nTop 15 nach In-Sample-Netto je Trade (Auswahl), daneben Out-of-Sample:")
print(f"{'TF':<4}{'Familie':<15}{'Param':<14}{'Trend':<6}{'Halten':>6}{'Stop':>5}{'IS n':>8}{'IS netto':>10}{'Treffer':>8}{'OOS n':>8}{'OOS netto':>10}")
for r in sorted(valid, key=lambda r: -r[7])[:15]:
    print(f"{r[0]:<4}{r[1]:<15}{str(r[2]):<14}{'ja' if r[3] else 'nein':<6}{r[4]:>6}{r[5]:>5}{r[6]:>8}{r[7]*100:>+9.3f}%{r[8]*100:>7.1f}%{r[9]:>8}{r[10]*100:>+9.3f}%")
