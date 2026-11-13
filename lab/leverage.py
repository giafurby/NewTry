"""
Hebel (Binance-Margin) auf die NewTry-Kombination: Was bringt geliehenes Geld, was kostet es?

Bei Hebel L werden Risiko je Trend-Trade (1 % × L), Höchstanteil je Position (33 % × L) und Crash-Kauf-Größe (20 % × L)
vervielfacht; gekauft werden darf bis zum L-fachen des Kapitals. Zinsen auf geliehenes USDC, Zwangsliquidation wie bei
Binance Cross-Margin (Vermögen/Schulden ≤ 1,1) mit den Tiefstkursen der Kerze, Liquidationsgebühr 1 %.
Bedingungen sonst wie im Maßstab (Kosten 0,20 % je Seite, Kauf 1 Minute nach dem Signal).

Aufruf: python -I lab/leverage.py <cache15> <cache1m>
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

import engine  # noqa: E402
import families as F  # noqa: E402
import stats  # noqa: E402
from data import load_market  # noqa: E402

COST = 0.002
BAR_YEARS = 15 / (60 * 24 * 365)


def run(ctx, start, lev, apr):
    m = ctx.m
    p = F.KOMBI_NEWTRY
    t, c = p["trend"], p["crash"]
    sigA, stopA, tgtA = F.trend_signals(ctx, t["n"], t["sl"], t["tp"])
    sigB, _ = F.crash_signals(ctx, c["x"], c["lb"])
    eq, liqs, interest = engine.sim_joint_lev(
        m.O, m.H, m.L, m.CF, m.EP, sigA, stopA, tgtA, int(t["mb"] * F.BARS_4H), 0.01 * lev, min(0.33 * lev, 0.99 * lev),
        3, 0.02, sigB, float(c["s"]), int(c["h"]), 0.20 * lev, 3, 96, COST, int(start), int(m.N), float(lev),
        float(apr * BAR_YEARS), 1.1, 0.01)
    return eq, liqs, interest


def main():
    m = load_market(sys.argv[1], sys.argv[2])
    ctx = F.Ctx(m)
    s18, s20, s25 = m.index_of("2018-01-01"), m.index_of("2020-01-01"), m.index_of("2025-01-01")

    # Abgleich: Hebel 1 muss die bekannte Kombi exakt ergeben
    ref, _ = F.run_kombi(ctx, F.KOMBI_NEWTRY, COST, s18, m.N)
    one, liqs, interest = run(ctx, s18, 1.0, 0.10)
    diff = float(np.nanmax(np.abs(ref[s18:] - one[s18:])))
    print(f"Abgleich Hebel 1 gegen run_kombi: größte Abweichung {diff:.2e} (muss 0 sein), Liquidationen {liqs}, Zinsen {interest}")

    print("\nHebel  Zins/Jahr  2020–10/2026      Rückgang  2022      seit 2025   Liquidationen")
    for apr in (0.08, 0.15):
        for lev in (1.0, 1.5, 2.0, 3.0, 5.0):
            eq, liqs, interest = run(ctx, s18, lev, apr)
            a = stats.metrics(eq, m.T, s20, m.N)
            b = stats.metrics(eq, m.T, s25, m.N)
            y22 = a["yearly"].get(2022, float("nan"))
            dead = " (Totalverlust)" if np.nanmin(eq[s18:]) <= 0 else ""
            print(f"{lev:>4.1f}×  {apr:>8.0%}  {a['cagr']:>+11.1%}/Jahr  {a['maxdd']:>7.0%}  {y22:>+6.0%}  {b['cagr']:>+9.1%}/Jahr"
                  f"  {liqs:>8}{dead}")
        print()

    # Kelly-Einordnung aus den Tagesrenditen der Kombi (ohne Hebel)
    for label, s in (("2020–10/2026", s20), ("seit 2025", s25)):
        d = stats.daily(ref, m.T, s, m.N).pct_change().dropna()
        mu, var = d.mean() * 365, d.var() * 365
        print(f"Kelly-Hebel {label}: μ {mu:+.1%}/Jahr, σ {math.sqrt(var):.1%}/Jahr → volles Kelly {mu / var:.1f}×, "
              f"halbes Kelly {mu / var / 2:.1f}×")


if __name__ == "__main__":
    main()
