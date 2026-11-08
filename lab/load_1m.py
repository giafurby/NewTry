"""1m-Parquet -> je Coin ein Ordner mit t.npy (int64 ms), o/h/l/c/v.npy (float64), mmap-fähig.
Aufruf: python -I load_1m.py <raw> <cache1m>"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAW, OUT = Path(sys.argv[1]), Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
for symdir in sorted((RAW / "data" / "interval_id=1m").iterdir()):
    symbol = symdir.name.split("=")[1]
    frames = [pd.read_parquet(p, columns=["timestamp", "open", "high", "low", "close", "volume"])
              for p in sorted(symdir.rglob("*.parquet"))]
    df = pd.concat(frames, ignore_index=True)
    ts = pd.to_datetime(df["timestamp"], utc=True)
    df["ts"] = ts.astype("int64") // (10**6 if ts.dt.unit == "ns" else 10**3 if ts.dt.unit == "us" else 1)
    df = df.sort_values("ts").drop_duplicates("ts")
    d = OUT / symbol
    d.mkdir(exist_ok=True)
    np.save(d / "t.npy", df["ts"].to_numpy("int64"))
    for k, col in zip("ohlcv", ("open", "high", "low", "close", "volume")):
        np.save(d / f"{k}.npy", df[col].to_numpy("float64"))
    t = df["ts"].to_numpy("int64")
    print(symbol, len(t), pd.Timestamp(t[0], unit="ms"), pd.Timestamp(t[-1], unit="ms"),
          "Lücken", int((np.diff(t) != 60_000).sum()), flush=True)
