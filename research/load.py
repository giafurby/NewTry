"""Parquet-Monatsdateien -> eine sortierte Tabelle je Coin und Zeitebene (npz-Cache) + Plausibilitätsprüfung.
Aufruf: python -I load.py <data_raw> <cache>"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAW, CACHE = Path(sys.argv[1]), Path(sys.argv[2])
CACHE.mkdir(parents=True, exist_ok=True)
STEP = {"15m": 900_000, "1h": 3_600_000, "1d": 86_400_000}

for interval in ("1h", "15m", "1d"):
    for symdir in sorted((RAW / "data" / f"interval_id={interval}").iterdir()):
        symbol = symdir.name.split("=")[1]
        frames = [pd.read_parquet(p) for p in sorted(symdir.rglob("*.parquet"))]
        df = pd.concat(frames, ignore_index=True)
        ts = pd.to_datetime(df["timestamp"], utc=True)
        df["ts"] = (ts.astype("int64") // 10**6) if ts.dt.unit == "ns" else ts.map(lambda t: int(t.timestamp() * 1000))
        df = df.sort_values("ts").drop_duplicates("ts")
        o, h, l, c, v = (df[k].to_numpy("float64") for k in ("open", "high", "low", "close", "volume"))
        t = df["ts"].to_numpy("int64")
        rows = df["source_rows"].to_numpy("int64") if "source_rows" in df else np.ones(len(df), "int64")
        bad = (h < np.maximum(o, c) - 1e-12) | (l > np.minimum(o, c) + 1e-12) | (l <= 0)
        gaps = np.diff(t) != STEP[interval]
        expected_rows = STEP[interval] // 60_000
        partial = rows < expected_rows
        np.savez_compressed(CACHE / f"{symbol}_{interval}.npz", t=t, o=o, h=h, l=l, c=c, v=v, rows=rows)
        print(f"{interval:>3} {symbol:<8} {len(t):>7} Kerzen  "
              f"{pd.Timestamp(t[0], unit='ms'):%Y-%m-%d} → {pd.Timestamp(t[-1], unit='ms'):%Y-%m-%d}  "
              f"OHLC-Fehler {int(bad.sum())}  Lücken {int(gaps.sum())} (größte {int(np.diff(t).max() // STEP[interval])} Kerzen)  "
              f"unvollständig {int(partial.sum())}")
