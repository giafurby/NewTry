"""Härtetest der Einbruch-Regel. Aufruf: python -I dip_stress.py <cache> <research-dir>"""
import sys

sys.path.insert(0, sys.argv[2])
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.argv = [sys.argv[0], sys.argv[1], "15m"]
import dip  # noqa: E402

N, SYM, T = dip.N, dip.SYMBOLS, dip.T
split = dip.split_i


def clean_signal(m, x):
    sig = dip.drop_signal(m, x)
    # keine Signale, wenn in den letzten M Kerzen eine Kerze fehlt (Wartungslücke statt echtem Einbruch)
    gap = np.zeros_like(sig)
    for k in range(0, m + 1):
        gap |= np.vstack([np.zeros((k, len(SYM)), bool), ~dip.live[: N - k]])
    return sig & ~gap


for m, x, hold in ((4, 0.05, 32), (16, 0.08, 16)):
    sig = clean_signal(m, x)
    print(f"\n=== Regel: Einbruch ≥{x:.0%} in {m} Kerzen (15m), {hold} Kerzen halten, 20 % je Position, max. 5 ===")
    print("Schlupf/Kosten je Seite und Notstop:")
    for cost in (0.0015, 0.003, 0.005):
        for stop in (0, 0.10, 0.15, 0.20):
            a = dip.simulate(sig, hold, stop, 0, 0.2, 5, cost, 0, split)
            b = dip.simulate(sig, hold, stop, 0, 0.2, 5, cost, split, N)
            print(f"  Kosten {cost:.2%} Stop {'ohne' if not stop else f'−{stop:.0%}':>5}: IS CAGR {a['cagr']:+7.1%} DD {a['mdd']:5.1%} "
                  f"Ø {a['avg']:+.2%} schlechtester {a['worst']:+.0%} | OOS CAGR {b['cagr']:+7.1%} DD {b['mdd']:5.1%} "
                  f"Ø {b['avg']:+.2%} schlechtester {b['worst']:+.0%}")
    full = dip.simulate(sig, hold, 0.15, 0, 0.2, 5, 0.003, 0, N, record=True)
    tr = pd.DataFrame(full["trades"], columns=["t", "j", "entry", "exit", "ret"])
    tr["year"] = pd.to_datetime(tr["t"], unit="ms").dt.year
    tr["coin"] = [SYM[j][:-4] for j in tr["j"]]
    tr["day"] = pd.to_datetime(tr["t"], unit="ms").dt.date
    ct, cv = full["curve"]
    curve = pd.Series(cv, index=pd.to_datetime(ct, unit="ms"))
    yearly = curve.groupby(curve.index.year).last() / curve.groupby(curve.index.year).first() - 1
    print("Pro Jahr (Kosten 0,30 %/Seite, Notstop −15 %): " + "  ".join(f"{y}: {r:+.0%}" for y, r in yearly.items()))
    print("Trades pro Jahr: " + "  ".join(f"{y}: {n}" for y, n in tr.groupby("year").size().items()))
    per_coin = tr.groupby("coin")["ret"].agg(["count", "mean"])
    print("Pro Coin (Ø je Trade): " + "  ".join(f"{c}: {r['mean']:+.2%} ({int(r['count'])})" for c, r in per_coin.iterrows()))
    days = tr.groupby("day")["ret"].sum().sort_values(ascending=False)
    print(f"Verschiedene Einbruch-Tage: {days.size}. Beste Tage: " + ", ".join(f"{d} {r:+.0%}" for d, r in days.head(5).items()))
    for drop in (5, 10, 20):
        keep = tr[~tr["day"].isin(days.head(drop).index)]
        print(f"  Ohne die {drop} besten Tage: Ø je Trade {keep['ret'].mean():+.2%} (vorher {tr['ret'].mean():+.2%}), "
              f"Summe {keep['ret'].sum():+.1f} statt {tr['ret'].sum():+.1f}")
    worst = tr.sort_values("ret").head(5)
    print("Schlechteste Trades: " + ", ".join(f"{r.coin} {pd.Timestamp(r.t, unit='ms'):%Y-%m-%d} {r.ret:+.0%}" for r in worst.itertuples()))
