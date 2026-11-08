"""
Portfolio-Auswahl (Schritt 7) per Walk-Forward: Für jedes Prüfjahr werden Töpfe (bis zu 3 Familien) und ihre Gewichte
(10-%-Schritte, Rest bleibt Cash) NUR mit Daten vor diesem Jahr gewählt – mit den Einstellungen, die jede Familie für
dieses Jahr gewählt hätte. Danach wird das Prüfjahr gehandelt.
Aufruf: python -I lab/portfolio.py <cache15> <cache1m> <ausgabe> [FAMILIE ...]
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import families as F  # noqa: E402
import research as R  # noqa: E402


def weight_sets(k):
    steps = [i / 10 for i in range(1, 11)]
    return [w for w in itertools.product(steps, repeat=k) if sum(w) <= 1.0 + 1e-9]


def main():
    cache15, cache1m, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    res = json.loads((out / "results.json").read_text(encoding="utf-8"))
    fams = sys.argv[4:] or list(res["families"])
    lab = R.Lab(cache15, cache1m)
    days = pd.to_datetime(lab.ht, unit="ms").floor("D")
    day_last = np.flatnonzero(np.r_[days[1:] != days[:-1], True])    # letzte Stunde jedes Tages

    curves = {}                                        # (fam, Prüfjahr) -> stündliche Kurve der gewählten Variante
    for fam in fams:
        for y in R.TEST_YEARS:
            p = res["families"][fam]["picks"][str(y)]
            key = json.dumps(p, sort_keys=True)
            if (fam, key) not in curves:
                eq, _ = lab.run(fam, {k: tuple(v) if isinstance(v, list) else v for k, v in p.items()}, R.COST)
                curves[(fam, key)] = lab.hourly(eq)
            curves[(fam, y)] = curves[(fam, key)]

    chain = [1.0]
    choice = {}
    for y in R.TEST_YEARS:
        cut = lab.year_cut[y]
        dl = day_last[day_last < cut]
        yrs = (lab.ht[cut - 1] - lab.ht[0]) / (365.25 * 86_400_000)
        best, best_score = None, -1e9
        for k in (1, 2, 3):
            ws = np.array(weight_sets(k))
            for subset in itertools.combinations(fams, k):
                D = np.vstack([curves[(f, y)][dl] for f in subset])           # Tageswerte im Training
                r = np.diff(D, axis=1) / D[:, :-1]
                combo = np.cumprod(1 + ws @ r, axis=1)
                combo = np.hstack([np.ones((len(ws), 1)), combo])
                g = np.log(combo[:, -1]) / yrs
                dd = (1 - combo / np.maximum.accumulate(combo, axis=1)).max(axis=1)
                score = g - 2.0 * np.maximum(0.0, dd - R.DD_FREE)
                i = int(np.argmax(score))
                if score[i] > best_score:
                    best_score, best = float(score[i]), (subset, tuple(float(x) for x in ws[i]))
        choice[y] = best
        lo, hi = lab.year_cut[y] - 1, lab.year_cut.get(y + 1, len(lab.ht))
        subset, w = best
        h = R.comb([curves[(f, y)][lo:hi] for f in subset], w)
        chain.extend(chain[-1] * h[1:] / h[0])
        print(y, "gewählt:", " + ".join(f"{f} {x:.0%}" for f, x in zip(subset, w)), f"(Ziel im Training {best_score:+.3f})",
              flush=True)
    oos = np.array(chain)
    t_oos = lab.oos_times()
    ew_h = lab.hourly(lab.run("HOLD", F.BENCHMARKS["ALLE_HALTEN"], R.COST)[0])
    lo = lab.year_cut[R.TEST_YEARS[0]] - 1
    ew = pd.Series(ew_h[lo:], index=pd.to_datetime(t_oos, unit="ms"))
    ew_daily = ew.groupby(ew.index.floor("D")).last()
    ev = lab.evaluate(oos, t_oos, ew_daily, n_trials=1)
    print(f"PORTFOLIO WF-OOS: {ev['cagr']:+.1%}/Jahr, DD {ev['maxdd']:.0%}, gesichert {ev['secured']:+.1%}, "
          f"Alpha {ev['alpha']['alpha']:+.1%} (t {ev['alpha']['alpha_t']:.1f}), Jahre {ev['yearly']}")
    np.save(out / "oos_PORTFOLIO.npy", oos)
    (out / "portfolio.json").write_text(json.dumps(dict(choice={y: [list(s), list(w)] for y, (s, w) in choice.items()},
                                                        oos=ev), indent=1, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
