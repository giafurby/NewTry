import sys, numpy as np, pandas as pd
from pathlib import Path
C = Path(sys.argv[1])
refs = [  # (Symbol, Datum UTC, 'high'/'low', bekannter Binance-Wert)
    ("BTCUSDT", "2017-12-17", "high", 19798.68), ("BTCUSDT", "2018-12-15", "low", 3156.26),
    ("BTCUSDT", "2020-03-13", "low", 3782.13), ("BTCUSDT", "2021-04-14", "high", 64854.00),
    ("BTCUSDT", "2021-11-10", "high", 69000.00), ("BTCUSDT", "2022-11-21", "low", 15476.00),
    ("BTCUSDT", "2024-03-14", "high", 73777.00), ("BTCUSDT", "2024-12-17", "high", 108353.00),
    ("BTCUSDT", "2025-01-20", "high", 109588.00), ("ETHUSDT", "2021-11-10", "high", 4868.00),
    ("ETHUSDT", "2022-06-18", "low", 880.00),
]
for sym, day, kind, known in refs:
    d = np.load(C / f"{sym}_1d.npz")
    t = pd.to_datetime(d["t"], unit="ms").strftime("%Y-%m-%d")
    i = np.flatnonzero(t == day)[0]
    got = d["h"][i] if kind == "high" else d["l"][i]
    print(f"{sym} {day} {kind:<4} Datensatz {got:>11.2f}  bekannt {known:>11.2f}  Abweichung {100*(got/known-1):+.3f} %")
# Zeitebenen gegeneinander: 15m -> 1h und 1h -> 1d müssen exakt passen
for sym in ("BTCUSDT", "SOLUSDT"):
    a = np.load(C / f"{sym}_15m.npz"); b = np.load(C / f"{sym}_1h.npz"); dd = np.load(C / f"{sym}_1d.npz")
    s15 = pd.DataFrame({k: a[k] for k in "tohlc"}).set_index(pd.to_datetime(a["t"], unit="ms"))
    agg = s15.resample("1h").agg({"o": "first", "h": "max", "l": "min", "c": "last"}).dropna()
    h1 = pd.DataFrame({k: b[k] for k in "ohlc"}, index=pd.to_datetime(b["t"], unit="ms"))
    j = agg.index.intersection(h1.index)
    print(sym, "15m→1h Abweichung max", float((agg.loc[j] - h1.loc[j]).abs().max().max()), "auf", len(j), "Stunden")
    agg2 = h1.resample("1D").agg({"o": "first", "h": "max", "l": "min", "c": "last"}).dropna()
    d1 = pd.DataFrame({k: dd[k] for k in "ohlc"}, index=pd.to_datetime(dd["t"], unit="ms"))
    j2 = agg2.index.intersection(d1.index)
    print(sym, "1h→1d Abweichung max", float((agg2.loc[j2] - d1.loc[j2]).abs().max().max()), "auf", len(j2), "Tagen")
# Jahresschlusskurse BTC zur Orientierung
d = np.load(C / "BTCUSDT_1d.npz"); s = pd.Series(d["c"], index=pd.to_datetime(d["t"], unit="ms"))
print("BTC Jahresschluss:", {y: round(float(s[str(y)].iloc[-1])) for y in range(2017, 2027)})
