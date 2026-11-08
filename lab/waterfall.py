"""
Überleitung: von der dokumentierten NewTry-Zahl (+77 %/Jahr, Rückgang 25 %) zur realistischen Erwartung.
Jeder Schritt ändert genau eine Annahme. Aufruf: python -I lab/waterfall.py <cache15> <cache1m>
Kombi = gemeinsames Depot wie im Bot (engine.sim_joint, gegen research/combo.py abgeglichen: +77,6 % statt +77,4 %).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402

import families as F  # noqa: E402
from data import load_market  # noqa: E402

def kombi(ctx, cost, start):
    eq, _ = F.run_kombi(ctx, F.KOMBI_NEWTRY, cost, start, ctx.m.N)
    return eq


def stats_of(m, eq, start, end=None, intraday=False):
    end = m.N if end is None else end
    s = pd.Series(eq[start:end], index=pd.to_datetime(m.T[start:end], unit="ms")).dropna()
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1
    d = s if intraday else s.groupby(s.index.floor("D")).first()
    dd = float((1 - d / d.cummax()).max())
    return cagr, dd


def main():
    m_open = load_market(sys.argv[1], None)
    m_real = load_market(sys.argv[1], sys.argv[2])
    c_open, c_real = F.Ctx(m_open), F.Ctx(m_real)
    s17, s18 = 0, m_open.index_of("2018-01-01")
    s20 = m_open.index_of("2020-01-01")
    s25 = m_open.index_of("2025-01-01")
    rows = [("Dokumentiert (NewTry ERGEBNISSE.md, gemeinsames Depot)", 0.774, 0.25)]
    e = kombi(c_open, 0.003, s17)
    rows.append(("Nachgerechnet (lab/engine.sim_joint), 2017–26, Kauf zur Eröffnung, 0,30 %",) + stats_of(m_open, e, s17))
    e = kombi(c_open, 0.003, s18)
    rows.append(("… ohne 2017 (Fehlprints, kaum Handel)",) + stats_of(m_open, e, s18))
    e = kombi(c_real, 0.003, s18)
    rows.append(("… Kauf 1 Minute nach Kerzenschluss",) + stats_of(m_real, e, s18))
    rows.append(("… Rückgang in jeder 15m-Kerze gemessen",) + stats_of(m_real, e, s18, intraday=True))
    e = kombi(c_real, 0.002, s18)
    rows.append(("… Kosten 0,20 % statt 0,30 % je Seite (Maßstab)",) + stats_of(m_real, e, s18, intraday=True))
    rows.append(("… nur Prüfzeitraum 2020–10/2026",) + stats_of(m_real, e, s20, intraday=True))
    rows.append(("… nur 2025–10/2026 (Seitwärts-/Abwärtsphase)",) + stats_of(m_real, e, s25, intraday=True))
    for name, cagr, dd in rows:
        print(f"{name:<60} {cagr:+7.1%} pro Jahr   größter Rückgang {dd:4.0%}")


if __name__ == "__main__":
    main()
