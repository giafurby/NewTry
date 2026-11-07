"""Risiko-Stufen der Kombination (Kosten 0,30 %). Aufruf: python -I risk.py <cache> <research-dir>"""
import sys
sys.path.insert(0, sys.argv[2])
import combo  # noqa: E402
base = dict(x=0.10, s=0.15, kb=3, c_b=0.33, hold_d=16, cooldown=96, cost=0.003)
for r_b, f_d, kd in ((0.0075, 0.15, 5), (0.0075, 0.20, 5), (0.01, 0.15, 5), (0.01, 0.20, 5), (0.01, 0.20, 3), (0.0125, 0.20, 5)):
    eq, tr = combo.run(r_b=r_b, f_d=f_d, kd=kd, **base)
    dd_end = (1 - eq / eq.cummax()).idxmax()
    combo.show(f"Trend {r_b:.2%} Risiko, Crash {f_d:.0%} max {kd}  (tiefster Punkt {dd_end:%Y-%m})", eq, tr)
