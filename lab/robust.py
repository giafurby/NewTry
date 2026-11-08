"""
Robustheit der Kandidaten (Schritt 5): Zufallsvergleich, jeder Coin einzeln weggelassen, Jahr für Jahr, Einstiegs-
verzögerung. Aufruf: python -I lab/robust.py <cache15> <cache1m> <ausgabe> FAMILIE=json-Parameter ...
Beispiel:   TREND4H='{"n":100,"sl":2.0,"tp":15.0,"mb":120}'
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

import families as F  # noqa: E402
import stats  # noqa: E402
from data import load_market  # noqa: E402

COST = 0.002
OOS_START = "2020-01-01"


def drop_coin(m, j):
    m2 = copy.copy(m)
    for name in ("O", "H", "L", "C", "CF", "V", "EP"):
        a = getattr(m, name).copy()
        a[:, j] = np.nan
        setattr(m2, name, a)
    live = m.live.copy()
    live[:, j] = False
    m2.live = live
    return m2


def signals_for_test(ctx, fam, p):
    """Einstiegsmaske und Ausstiegsparameter für den Zufallsvergleich (nur Familien mit Einzel-Trades)."""
    m = ctx.m
    if fam == "TREND4H":
        sig, stopf, tgtf = F.trend_signals(ctx, p["n"], p["sl"], p["tp"])
        return sig, stopf, tgtf, np.zeros((m.N, m.K)), p["mb"] * F.BARS_4H
    if fam == "CRASH":
        sig, _ = F.crash_signals(ctx, p["x"], p["lb"])
        return sig, np.full((m.N, m.K), p["s"]), np.full((m.N, m.K), np.inf), np.zeros((m.N, m.K)), p["h"]
    return None


def main():
    cache15, cache1m, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    cands = {}
    for arg in sys.argv[4:]:
        label, _, js = arg.partition("=")
        cands[label] = (label.split(":")[-1], json.loads(js))     # NAME:FAMILIE=json
    m = load_market(cache15, cache1m)
    m0 = load_market(cache15, None)                  # Einstieg zur Kerzeneröffnung (wie NewTry) zum Vergleich
    start, oos = m.index_of("2018-01-01"), m.index_of(OOS_START)
    report = {}
    for label, (fam, p) in cands.items():
        run = F.FAMILIES[fam][1]
        ctx = F.Ctx(m)
        r = {}
        eq, _ = run(ctx, p, COST, start, m.N)
        base = stats.metrics(eq, m.T, oos, m.N)
        r["base"] = dict(cagr=base["cagr"], maxdd=base["maxdd"], yearly=base["yearly"])
        eq0, _ = run(F.Ctx(m0), p, COST, start, m.N)
        b0 = stats.metrics(eq0, m.T, oos, m.N)
        r["entry_at_open"] = dict(cagr=b0["cagr"], maxdd=b0["maxdd"])
        # jeder Coin einzeln weggelassen
        loco = {}
        for j, s in enumerate(m.symbols):
            e, _ = run(F.Ctx(drop_coin(m, j)), p, COST, start, m.N)
            mm = stats.metrics(e, m.T, oos, m.N)
            loco[s[:-4]] = dict(cagr=mm["cagr"], maxdd=mm["maxdd"])
        r["leave_one_out"] = loco
        # ohne das beste Jahr
        ys = base["yearly"]
        best_y = max(ys, key=ys.get)
        rest = [v for y, v in ys.items() if y != best_y]
        r["without_best_year"] = dict(year=best_y, cagr=float(np.exp(np.mean(np.log1p(rest))) - 1))
        # Zufallsvergleich
        t = signals_for_test(ctx, fam, p)
        if t is not None:
            sig, stopf, tgtf, trailf, hold = t
            r["random_entry"] = stats.random_entry_test(m, sig, stopf, tgtf, trailf, hold, COST, oos, m.N, iters=300)
            r["random_entry_full"] = stats.random_entry_test(m, sig, stopf, tgtf, trailf, hold, COST, start, m.N, iters=300)
        report[label] = r
        print(label, json.dumps(r, default=float)[:3000], flush=True)
    (out / "robust.json").write_text(json.dumps(report, indent=1, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
