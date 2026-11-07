"""Stabilitätsprüfung der Kombination. Aufruf: python -I robust.py <cache> <research-dir>"""
import sys
sys.path.insert(0, sys.argv[2])
import pandas as pd  # noqa: E402
import combo  # noqa: E402

base = dict(x=0.10, f_d=0.2, kd=3, s=0.15, r_b=0.01, cost=0.003, cooldown=96)
def go(name, **kw):
    cfg = {**base, **kw}
    eq, tr = combo.run(**cfg)
    combo.show(name, eq, tr)
    return eq
print("Kosten 0,30 %/Seite, Basis = FINAL: Trend 1 %/max 3 + Crash −10 %/4 h, 20 %, max 3, Stop −15 %, 4 h, Sperre 24 h")
eq = go("BASIS")
for x in (0.09, 0.12, 0.15):
    go(f"Schwelle −{x:.0%}", x=x)
for h in (8, 32):
    go(f"Haltedauer {h * 15 // 60} h", hold_d=h)
for st in (0.10, 0.20):
    go(f"Notstop −{st:.0%}", s=st)
go("ohne Sperre", cooldown=0)
go("Sperre 48 h nach Notstop", cooldown=192)
go("nur Trend", use_dip=False)
go("nur Crash-Kauf", use_trend=False)
go("Kosten 0,15 %", cost=0.0015)
go("Kosten 0,50 %", cost=0.005)
go("Einbruch nur BTC/ETH/SOL/BNB/XRP", dip_coins={"BTC", "ETH", "SOL", "BNB", "XRP"})
go("Trend 1,5 % Risiko", r_b=0.015)
go("Crash 25 % je Position", f_d=0.25)
monthly = eq.resample("ME").last().pct_change().dropna()
print(f"\nBASIS Monate: {len(monthly)}, davon im Minus {int((monthly < 0).sum())} ({(monthly < 0).mean():.0%}), "
      f"schlechtester {monthly.min():+.1%} ({monthly.idxmin():%Y-%m}), bester {monthly.max():+.1%} ({monthly.idxmax():%Y-%m})")
for start in ("2019-01-01", "2020-01-01", "2021-01-01", "2022-01-01", "2024-01-01", "2025-01-01"):
    e = eq[eq.index >= start]
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    print(f"Start {start}: {(e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1:+.1%} pro Jahr, größter Rückgang {(1 - e / e.cummax()).max():.0%}, "
          f"aus 150 € würden {150 * e.iloc[-1] / e.iloc[0]:,.0f} €")
