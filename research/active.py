"""Was hätte 'viel handeln' seit 2025 gebracht? Und mehr Crash-Käufe ohne Schaden? Aufruf: python -I active.py <cache> <research>"""
import sys
sys.path.insert(0, sys.argv[2])
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
import combo  # noqa: E402
import dip  # noqa: E402
from daytrade import rsi  # noqa: E402

START = 159.69
T, N, CL, H = dip.T, dip.N, dip.CL, dip.H
i25 = int(np.searchsorted(T, int(pd.Timestamp("2025-01-01").timestamp() * 1000)))
years = (T[-1] - T[i25]) / (365.25 * 86_400_000)
rsi2 = np.column_stack([rsi(np.nan_to_num(CL[:, j], nan=np.nanmean(CL[:, j])), 2) for j in range(CL.shape[1])])
prior_high = pd.DataFrame(H).shift(1).rolling(48, min_periods=48).max().to_numpy()
with np.errstate(invalid="ignore"):
    rules = {
        "Rücksetzer kaufen (RSI2 < 10), 2 h halten": dip.live & (rsi2 < 10),
        "Ausbruch über 12-h-Hoch, 2 h halten": dip.live & (CL > prior_high),
        "Immer im Markt, alle 2 h neu kaufen": dip.live.copy(),
    }
print(f"Zeitraum 01.01.2025 – 30.10.2026 ({years:.1f} Jahre), Start {START} USDC, Kosten 0,15 % je Seite (normal), "
      "je Position 33 %, max. 3 gleichzeitig")
for name, sig in rules.items():
    r = dip.simulate(sig, 8, 0, 0, 0.33, 3, 0.0015, i25, N)
    print(f"  {name:<45} {r['n']:>6} Trades ({r['n'] / years / 365:.1f} pro Tag) → {START * r['final']:8.2f} USDC "
          f"(größter Rückgang {r['mdd']:.0%})")
for label, kw in (("JETZIGER BOT (Trend + Crash −10 %, 4 h)", {}), ("Crash ab −9 %, 4 h", {"x": 0.09}),
                  ("Crash ab −8 %, 4 h", {"x": 0.08}), ("Crash ab −9 %, 2 h", {"x": 0.09, "hold_d": 8})):
    cfg = dict(x=0.10, f_d=0.2, kd=3, s=0.15, r_b=0.01, cooldown=96, hold_d=16, **{})
    cfg.update(kw)
    eq, tr = combo.run(cost=0.0015, start=i25, **cfg)
    n = len(tr)
    full, _ = combo.run(cost=0.003, **cfg)
    a = full[full.index < "2023-01-01"]; b = full[full.index >= "2023-01-01"]
    st = lambda e: ((e.iloc[-1] / e.iloc[0]) ** (365.25 / (e.index[-1] - e.index[0]).days) - 1, (1 - e / e.cummax()).max())
    print(f"  {label:<45} {n:>6} Trades ({n / years / 365:.2f} pro Tag) → {START * eq.iloc[-1] / eq.iloc[0]:8.2f} USDC | "
          f"2017–22: {st(a)[0]:+.0%}/DD {st(a)[1]:.0%} · 2023–26: {st(b)[0]:+.0%}/DD {st(b)[1]:.0%} (0,30 % Kosten)")
