"""Crash-Kauf: Ausführungsrealität mit 1m-Daten (Abschnitt 3 in ERGEBNISSE_V2.md).
Aufruf: python -I lab/dip_exec_check.py <cache15> <NewTry/research> <cache1m>"""
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[2])
C1 = Path(sys.argv[3])
sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import combo  # noqa: E402

cfg = dict(x=0.09, f_d=0.2, kd=3, s=0.15, r_b=0.01, cost=0.003, cooldown=96, hold_d=16)
eq, tr = combo.run(use_trend=False, **cfg)
t = pd.DataFrame(tr, columns=["kind", "t", "j", "ret"])
t["coin"] = [combo.SYM[j] for j in t["j"]]
print(f"Crash-Trades: {len(t)}, Ø {t['ret'].mean():+.3%}, Median {t['ret'].median():+.3%}")
print("Größte Gewinne:")
print(t.sort_values("ret", ascending=False).head(6).assign(t=lambda d: pd.to_datetime(d["t"], unit="ms")).to_string())

m1 = {}
for s in combo.SYM:
    d = C1 / s
    m1[s] = {k: np.load(d / f"{k}.npy", mmap_mode="r") for k in "tohlc"}

COST = 0.003
rows = []
for r in t.itertuples():
    d = m1[r.coin]
    i0 = int(np.searchsorted(d["t"], r.t))           # Einstieg = Open der 15m-Kerze nach dem Signal = Open dieser Minute
    if i0 >= len(d["t"]) or int(d["t"][i0]) != r.t:
        continue
    exit_ts = r.t + 16 * 900_000 - 60_000              # letzte Minute der 16. Kerze
    i1 = int(np.searchsorted(d["t"], exit_ts))
    if i1 >= len(d["t"]):
        continue
    entry = float(d["o"][i0])
    exit_close = float(d["c"][i1])
    stop = entry * 0.85
    lows = np.asarray(d["l"][i0:i1 + 1])
    hit = np.flatnonzero(lows <= stop)
    base_exit = min(stop, float(d["o"][i0 + hit[0]])) if hit.size else exit_close
    res = {"t": r.t, "coin": r.coin, "ret15": r.ret, "base": base_exit / entry * (1 - COST) ** 2 - 1}
    for delay in (1, 2, 5):
        e2 = float(d["o"][i0 + delay])
        lows2 = np.asarray(d["l"][i0 + delay:i1 + 1])
        st2 = e2 * 0.85
        h2 = np.flatnonzero(lows2 <= st2)
        x2 = min(st2, float(d["o"][i0 + delay + h2[0]])) if h2.size else exit_close
        res[f"d{delay}"] = x2 / e2 * (1 - COST) ** 2 - 1
    res["worst1"] = base_exit / float(d["h"][i0]) * (1 - COST) ** 2 - 1   # Kauf zum Höchstkurs der ersten Minute
    rows.append(res)
R = pd.DataFrame(rows)
print(f"\n1m-Nachrechnung: {len(R)} Trades")
for col, label in (("ret15", "15m-Simulation"), ("base", "1m, Kauf Minute 0 (wie Simulation)"), ("d1", "1 Minute später"),
                   ("d2", "2 Minuten später"), ("d5", "5 Minuten später"), ("worst1", "zum Hoch der 1. Minute")):
    v = R[col]
    print(f"  {label:<38} Ø {v.mean():+.3%}  Median {v.median():+.3%}  Summe {v.sum():+.2f}")
R["year"] = pd.to_datetime(R["t"], unit="ms").dt.year
print("\nØ je Jahr (Minute 0 / 1 Min später / Hoch 1. Minute):")
for y, g in R.groupby("year"):
    print(f"  {y}: n={len(g):>3}  {g['base'].mean():+.2%}  {g['d1'].mean():+.2%}  {g['worst1'].mean():+.2%}")
be = R["base"].mean() + 2 * COST
print(f"\nBreak-even Kosten je Seite (Ø brutto / 2): {be / 2:.2%}")
