"""Endgültige Konfiguration. Aufruf: python -I final.py <cache> <research-dir>"""
import sys
sys.path.insert(0, sys.argv[2])
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import combo  # noqa: E402

final = dict(x=0.10, f_d=0.2, kd=5, s=0.15, r_b=0.01, kb=3, c_b=0.33, hold_d=16, cooldown=96)
for cost in (0.003, 0.0015):
    for name, kw in (("FINAL (Sperre 24 h)", {}), ("ohne Sperre", {"cooldown": 0})):
        eq, tr = combo.run(cost=cost, **{**final, **kw})
        combo.show(f"{name}, Kosten {cost:.2%}", eq, tr)
eq, tr = combo.run(cost=0.003, **final)
t = pd.DataFrame(tr, columns=["kind", "t", "j", "ret"])
t["year"] = pd.to_datetime(t["t"], unit="ms").dt.year
t["coin"] = [combo.SYM[j][:-4] for j in t["j"]]
for kind in ("trend", "dip"):
    s = t[t["kind"] == kind]
    print(f"\n{kind}: {len(s)} Trades, Treffer {(s['ret'] > 0).mean():.0%}, Ø {s['ret'].mean():+.2%}, Median {s['ret'].median():+.2%}, "
          f"bester {s['ret'].max():+.0%}, schlechtester {s['ret'].min():+.0%}")
    print("  pro Jahr: " + "  ".join(f"{y}: {n}" for y, n in s.groupby("year").size().items()))
    print("  pro Coin Ø: " + "  ".join(f"{c} {m:+.1%}" for c, m in s.groupby("coin")["ret"].mean().items()))
# Ein LUNA-Szenario: ein Coin fällt in 4 Tagen von 80 auf 0,0001 – wie oft kauft die Einbruch-Regel und was kostet es?
for cd in (0, 96):
    prices = 80 * np.exp(np.linspace(0, np.log(0.0001 / 80), 4 * 96))       # stetiger Absturz in 15m-Schritten
    noise = 1 + 0.02 * np.sin(np.arange(len(prices)) / 3)                   # mit Zwischenerholungen
    p = prices * noise
    loss, i, n = 0.0, 16, 0
    while i < len(p) - 1:
        if p[i] / p[i - 16] - 1 <= -0.10:
            entry = p[i + 1]; n += 1
            k = i + 1
            while k < min(i + 17, len(p)) and p[k] > entry * 0.85:
                k += 1
            exit_px = max(min(p[min(k, len(p) - 1)], entry), 0)
            r = min(exit_px / entry, 0.85 if k < i + 17 else exit_px / entry) - 1
            loss += 0.2 * (r - 0.006)
            i = k + (cd if k < i + 17 else 0) + 1
        else:
            i += 1
    print(f"LUNA-Szenario, Sperre {cd // 4} h: {n} Käufe, Kapitalverlust ca. {loss:.0%}")
