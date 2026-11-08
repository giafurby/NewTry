"""
Referenzwerte für die Live-Wächter des Bots (Schritt 8) – aus derselben Simulation wie der Maßstab.

  1. Einstiegsdrift: Wie weit liegt der simulierte Kaufkurs (2. Minute) im Mittel über/unter dem Signal-Schluss?
     Der Ausführungswächter vergleicht die echten Käufe damit.
  2. Vorwärtstest: Verteilung des Durchschnitts von 20 bzw. 30 aufeinanderfolgenden Trades je Regel (Block-Bootstrap über
     die Trade-Reihe 2018–2026). Liegt der Live-Durchschnitt unter dem 5-%-Quantil, passt der Markt nicht mehr zur Regel.
  3. Risikostufen: Rendite und Rückgang bei anderem Trend-Risiko und anderer Crash-Größe (nur zur Einordnung).
Aufruf: python -I lab/live_reference.py <cache15> <cache1m> [--cash]   (--cash: nur der investierte Anteil der Kombi)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import families as F  # noqa: E402
import stats  # noqa: E402
from data import load_market  # noqa: E402

COST = 0.002


def main():
    m = load_market(sys.argv[1], sys.argv[2])
    ctx = F.Ctx(m)
    s18, s20, s25 = m.index_of("2018-01-01"), m.index_of("2020-01-01"), m.index_of("2025-01-01")
    eq, tr = F.run_kombi(ctx, F.KOMBI_NEWTRY, COST, s18, m.N)
    df = pd.DataFrame(tr, columns=["eb", "xb", "j", "entry", "exit", "ret", "why", "kind", "weight"])
    df["sig"] = df["eb"].astype(int) - 1
    df["close"] = m.C[df["sig"], df["j"].astype(int)]
    df["drift"] = df["entry"] / df["close"] - 1
    df["year"] = pd.to_datetime(m.T[df["eb"].astype(int)], unit="ms").year
    for k, name in ((0, "Trend"), (1, "Crash")):
        d = df[df["kind"] == k]
        print(f"\n{name}: {len(d)} Trades 2018–26, Ø {d['ret'].mean():+.2%}, Median {d['ret'].median():+.2%}, "
              f"Treffer {(d['ret'] > 0).mean():.0%}")
        print(f"  Einstiegsdrift Schluss→Kauf (2. Minute): Ø {d['drift'].mean():+.3%}, Median {d['drift'].median():+.3%}, "
              f"90 % {d['drift'].quantile(0.9):+.3%}")
        r = d["ret"].to_numpy()
        rng = np.random.default_rng(1)
        for n in (20, 30):
            means = []
            for _ in range(20000):
                start = rng.integers(0, len(r) - n)
                means.append(r[start:start + n].mean())           # zusammenhängende Blöcke (Marktphasen bleiben)
            q = np.quantile(means, [0.05, 0.5])
            print(f"  Ø von {n} aufeinanderfolgenden Trades: 5-%-Quantil {q[0]:+.2%}, Median {q[1]:+.2%}")
        print("  Ø je Jahr: " + "  ".join(f"{y}: {g['ret'].mean():+.2%} ({len(g)})" for y, g in d.groupby("year")))
    print("\nRisikostufen (2020–10/2026, Kosten 0,20 %, 1 Minute Verzögerung):")
    for risk, size in ((0.0075, 0.15), (0.01, 0.10), (0.01, 0.20), (0.015, 0.20)):
        e, _ = F.run_kombi(ctx, {**F.KOMBI_NEWTRY, "risk": risk, "size": size}, COST, s18, m.N)
        a = stats.metrics(e, m.T, s20, m.N)
        b = stats.metrics(e, m.T, s25, m.N)
        print(f"  Trend {risk:.2%} Risiko, Crash {size:.0%}: {a['cagr']:+.1%}/Jahr, Rückgang {a['maxdd']:.0%}, "
              f"schlechtester Monat {a['worst_month']:+.0%} | seit 2025: {b['cagr']:+.1%}/Jahr, Rückgang {b['maxdd']:.0%}")


if __name__ == "__main__" and "--cash" not in sys.argv:
    main()


def idle_cash(cache15, cache1m):
    """Teil E der Gemini-Recherche: Wie viel Kapital ist im Mittel investiert (Rest liegt als USDC herum)?"""
    m = load_market(cache15, cache1m)
    ctx = F.Ctx(m)
    s18, s25 = m.index_of("2018-01-01"), m.index_of("2025-01-01")
    _, tr = F.run_kombi(ctx, F.KOMBI_NEWTRY, COST, s18, m.N)
    for label, start in (("2018–10/2026", s18), ("2025–10/2026", s25)):
        exposure = np.zeros(m.N)
        for eb, xb, w in zip(tr[:, 0].astype(int), tr[:, 1].astype(int), tr[:, 8]):
            exposure[max(eb, start):xb + 1] += w
        e = exposure[start:]
        print(f"Kombi {label}: im Mittel {e.mean():.0%} investiert, {np.mean(e < 0.05):.0%} der Zeit (fast) ganz in USDC")


if __name__ == "__main__" and len(sys.argv) > 3 and sys.argv[3] == "--cash":
    idle_cash(sys.argv[1], sys.argv[2])
