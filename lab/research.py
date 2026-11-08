"""
Forschungsrunde v2: alle Familien unter identischen Bedingungen, Walk-Forward, gemeinsamer Maßstab (MASSSTAB.md).

Aufruf (Arbeitsordner außerhalb der Daten, heruntergeladene Dateien werden nie als Code ausgeführt):
  python -I lab/research.py <cache15> <cache1m> <ausgabe-ordner>
Ergebnis: <ausgabe>/results.json (alle Zahlen) und eine Zusammenfassung auf der Konsole.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import families as F  # noqa: E402
import stats  # noqa: E402
from data import load_market  # noqa: E402

COST = 0.002
STRESS = 0.004
START = "2018-01-01"
TEST_YEARS = list(range(2020, 2027))
HOUR = 3_600_000
DD_FREE = 0.30          # Rückgänge bis 30 % kosten im Auswahl-Ziel nichts, darüber doppelt


def objective(h: np.ndarray, years: float) -> float:
    h = h[np.isfinite(h)]
    if len(h) < 2 or h[0] <= 0 or h[-1] <= 0:
        return -9.0
    g = math.log(h[-1] / h[0]) / years
    dd = float((1 - h / np.maximum.accumulate(h)).max())
    return g - 2.0 * max(0.0, dd - DD_FREE)


class Lab:
    def __init__(self, cache15, cache1m):
        t = time.time()
        self.m = load_market(cache15, cache1m)
        self.ctx = F.Ctx(self.m)
        self.start = self.m.index_of(START)
        self.end = self.m.N
        T = self.m.T
        last_of_hour = ((T + 900_000) % HOUR) == 0
        self.hidx = np.flatnonzero(last_of_hour & (np.arange(self.m.N) >= self.start))
        self.ht = T[self.hidx] + 900_000                  # Zeitpunkt = Ende der Stunde
        self.year_cut = {y: int(np.searchsorted(self.ht, int(pd.Timestamp(f"{y}-01-01", tz="UTC").timestamp() * 1000)))
                         for y in TEST_YEARS + [2027]}
        print(f"Daten geladen ({time.time() - t:.0f} s): {self.m.N} Kerzen, {len(self.hidx)} Stunden ab {START}", flush=True)

    # ------------------------------------------------------------------ Läufe
    def hourly(self, eq):
        h = eq[self.hidx].astype(np.float64)
        return h

    def run(self, fam, p, cost):
        if fam in F.FAMILIES:
            return F.FAMILIES[fam][1](self.ctx, p, cost, self.start, self.end)
        if fam == "KOMBI":
            return F.run_kombi(self.ctx, p, cost, self.start, self.end)
        return F.run_hold(self.ctx, p, cost, self.start, self.end)

    def grid(self, fam, cost):
        grid = F.FAMILIES[fam][0]
        H = np.empty((len(grid), len(self.hidx)))
        trades = []
        for v, p in enumerate(grid):
            eq, extra = self.run(fam, p, cost)
            H[v] = self.hourly(eq)
            trades.append(len(extra) if isinstance(extra, np.ndarray) else extra.get("orders", 0))
        return H, trades

    # ------------------------------------------------------------------ Walk-Forward
    def walk_forward(self, H):
        picks = {}
        chain = [1.0]
        for y in TEST_YEARS:
            a, b = 0, self.year_cut[y]
            yrs = (self.ht[b - 1] - self.ht[0]) / (365.25 * 86_400_000)
            scores = [objective(H[v, a:b], yrs) for v in range(len(H))]
            v = int(np.argmax(scores))
            picks[y] = v
            lo, hi = self.year_cut[y] - 1, self.year_cut[y + 1] if y + 1 in self.year_cut else len(self.ht)
            seg = H[v, lo:hi]
            chain.extend(chain[-1] * seg[1:] / seg[0])
        oos = np.array(chain)
        return picks, oos

    def oos_times(self):
        lo = self.year_cut[TEST_YEARS[0]] - 1
        return self.ht[lo:]

    # ------------------------------------------------------------------ Bewertung nach dem Maßstab
    def evaluate(self, h, t, market_daily=None, n_trials=1, sr_var=0.0, label=""):
        res = stats.metrics(h, t, 0, len(h))
        d = pd.Series(h, index=pd.to_datetime(t, unit="ms"))
        d = d.groupby(d.index.floor("D")).last()
        r = d.pct_change().dropna().to_numpy()
        res["boot"] = stats.bootstrap(r)
        res["secured"] = math.exp(res["boot"]["growth_p10"]) - 1
        res["dsr"] = stats.deflated_sharpe(res["sr_daily"], len(r), res["skew"], res["kurt"], n_trials, sr_var)
        if market_daily is not None:
            res["alpha"] = stats.alpha_vs(d, market_daily)
        return res


def comb(H_list, w):
    """Konstante Gewichte über Töpfe (stündlich auf Zielgewicht), Rest Cash."""
    rets = np.vstack([np.diff(h) / h[:-1] for h in H_list])
    r = np.asarray(w) @ rets
    return np.concatenate([[1.0], np.cumprod(1 + r)])


def main():
    cache15, cache1m, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    lab = Lab(cache15, cache1m)
    t_oos = lab.oos_times()
    report = {"meta": dict(cost=COST, stress=STRESS, start=START, test_years=TEST_YEARS, hours=len(lab.hidx)),
              "families": {}, "fixed": {}, "benchmarks": {}}

    # ---------------------------------------------------------------- Maßstäbe
    bench_h = {}
    for name, p in F.BENCHMARKS.items():
        eq, _ = lab.run("HOLD", p, COST)
        bench_h[name] = lab.hourly(eq)
    lo = lab.year_cut[TEST_YEARS[0]] - 1
    ew = pd.Series(bench_h["ALLE_HALTEN"][lo:], index=pd.to_datetime(t_oos, unit="ms"))
    ew_daily = ew.groupby(ew.index.floor("D")).last()
    for name, h in bench_h.items():
        seg = h[lo:] / h[lo]
        report["benchmarks"][name] = lab.evaluate(seg, t_oos, ew_daily if name != "ALLE_HALTEN" else None)

    # ---------------------------------------------------------------- Familien
    all_sr = []
    fam_var = {}
    fam_H = {}
    for fam in F.FAMILIES:
        t = time.time()
        H, ntr = lab.grid(fam, COST)
        Hs, _ = lab.grid(fam, STRESS)
        fam_H[fam] = H
        picks, oos = lab.walk_forward(H)
        _, oos_s = lab.walk_forward(Hs)
        # Rückblick-Bester über die ganze Zeit (nur zur Messung der Auswahl-Verzerrung)
        yrs_full = (lab.ht[-1] - lab.ht[0]) / (365.25 * 86_400_000)
        full_scores = np.array([objective(H[v], yrs_full) for v in range(len(H))])
        best = int(np.argmax(full_scores))
        # Kennzahlen aller Varianten im OOS-Zeitraum (für Nachbarschaft und DSR)
        g_oos = np.array([math.log(H[v, -1] / H[v, lo]) / ((lab.ht[-1] - lab.ht[lo]) / (365.25 * 86_400_000)) for v in range(len(H))])
        srs = []
        for v in range(len(H)):
            s = pd.Series(H[v], index=pd.to_datetime(lab.ht, unit="ms"))
            dr = s.groupby(s.index.floor("D")).last().pct_change().dropna()
            srs.append(float(dr.mean() / dr.std()) if dr.std() > 0 else 0.0)
        all_sr.extend(srs)
        fam_var[fam] = (len(srs), float(np.var(srs)))
        hb = H[best]
        full_best = lab.evaluate(hb, lab.ht, None, n_trials=len(H), sr_var=float(np.var(srs)))
        res = lab.evaluate(oos, t_oos, ew_daily)
        res_s = stats.metrics(oos_s, t_oos, 0, len(oos_s))
        deploy = F.FAMILIES[fam][0][picks[TEST_YEARS[-1]]]
        report["families"][fam] = dict(
            variants=len(H), picks={y: F.FAMILIES[fam][0][v] for y, v in picks.items()}, deploy=deploy,
            oos=res, oos_stress=dict(growth=res_s["growth"], cagr=res_s["cagr"], maxdd=res_s["maxdd"]),
            hindsight_best=dict(params=F.FAMILIES[fam][0][best], cagr=full_best["cagr"], maxdd=full_best["maxdd"],
                                dsr=full_best["dsr"]),
            grid_oos=dict(share_positive=float((g_oos > 0).mean()), median_cagr=float(np.exp(np.median(g_oos)) - 1),
                          best_cagr=float(np.exp(g_oos.max()) - 1)),
            trades_deploy=ntr[picks[TEST_YEARS[-1]]])
        np.save(out / f"oos_{fam}.npy", oos)
        np.save(out / f"oos_stress_{fam}.npy", oos_s)
        print(f"{fam:<10} {len(H):>4} Varianten in {time.time() - t:5.0f} s | WF-OOS {res['cagr']:+7.1%}/Jahr, "
              f"DD {res['maxdd']:4.0%}, gesichert {res['secured']:+7.1%}, Stress {res_s['cagr']:+7.1%} | "
              f"Rückblick-Bester {full_best['cagr']:+7.1%}", flush=True)
    np.save(out / "oos_times.npy", t_oos)

    # ---------------------------------------------------------------- vorab festgelegte Konfigurationen
    sr_var_all = float(np.var(all_sr))
    n_all = len(all_sr)
    # Streuung der Sharpe-Werte INNERHALB der Familien (gepoolt): die passende Null-Streuung für die DSR. Die Streuung über
    # alle Familien enthält echte Unterschiede (z. B. die klar negativen Gemini-Varianten) und überschätzt das Glück.
    sr_var_pooled = sum(n * v for n, v in fam_var.values()) / sum(n for n, _ in fam_var.values())
    fixed = {
        "NEWTRY_TREND": [("TREND4H", F.TREND_NEWTRY, 1.0)],
        "NEWTRY_CRASH": [("CRASH", F.CRASH_NEWTRY, 1.0)],
        "NEWTRY_KOMBI": [("KOMBI", F.KOMBI_NEWTRY, 1.0)],
        "KOMBI_CRASH_10": [("KOMBI", {**F.KOMBI_NEWTRY, "size": 0.10}, 1.0)],      # nur Empfindlichkeit
        "KOMBI_CRASH_AB_10": [("KOMBI", {**F.KOMBI_NEWTRY, "crash": {**F.CRASH_NEWTRY, "x": 0.10}}, 1.0)],
        "GEMINI_A_PULLBACK": [("PULLBACK", F.PULLBACK_GEMINI, 1.0)],
        "GEMINI_B_TRANCHE": [("TRANCHE", F.TRANCHE_GEMINI, 1.0)],
        "GEMINI_HYBRID": [("PULLBACK", F.PULLBACK_GEMINI, 0.5), ("TRANCHE", F.TRANCHE_GEMINI, 0.5)],
        **{f"GEMINI2_{fam}": [(fam, p, 1.0)] for fam, p in F.GEMINI2_DEFAULTS.items()},
    }
    segs = {}
    for name, parts in fixed.items():
        hs, hs_s, ws, ntr = [], [], [], 0
        for fam, p, w in parts:
            eq, extra = lab.run(fam, p, COST)
            hs.append(lab.hourly(eq))
            eq_s, _ = lab.run(fam, p, STRESS)
            hs_s.append(lab.hourly(eq_s))
            ws.append(w)
            ntr += len(extra) if isinstance(extra, np.ndarray) else 0
        h = comb(hs, ws)
        h_s = comb(hs_s, ws)
        seg, seg_s = h[lo:] / h[lo], h_s[lo:] / h_s[lo]
        res = lab.evaluate(seg, t_oos, ew_daily, n_trials=n_all, sr_var=sr_var_pooled)
        res["dsr_naive_all_families"] = stats.deflated_sharpe(res["sr_daily"], res["days"], res["skew"], res["kurt"], n_all,
                                                              sr_var_all)
        res_full = stats.metrics(h, lab.ht, 0, len(h))
        res_s = stats.metrics(seg_s, t_oos, 0, len(seg_s))
        report["fixed"][name] = dict(parts=[(f, p, w) for f, p, w in parts], oos=res,
                                     oos_stress=dict(cagr=res_s["cagr"], maxdd=res_s["maxdd"]),
                                     full=dict(cagr=res_full["cagr"], maxdd=res_full["maxdd"], yearly=res_full["yearly"]),
                                     trades_full=ntr)
        np.save(out / f"fixed_{name}.npy", seg)
        segs[name] = seg
        print(f"{name:<18} 2020–26 {res['cagr']:+7.1%}/Jahr, DD {res['maxdd']:4.0%}, gesichert {res['secured']:+7.1%}, "
              f"Stress {res_s['cagr']:+7.1%} | 2018–26 {res_full['cagr']:+7.1%}, DD {res_full['maxdd']:4.0%} | "
              f"DSR {res['dsr']:.2f} (naiv {res['dsr_naive_all_families']:.2f})", flush=True)

    # ---------------------------------------------------------------- Runde 2b: Ergänzungs-Prüfung (MASSSTAB.md, Nachtrag)
    kombi = segs["NEWTRY_KOMBI"]
    report["blend_2b"] = {}
    base = report["fixed"]["NEWTRY_KOMBI"]["oos"]
    kd = pd.Series(kombi, index=pd.to_datetime(t_oos, unit="ms"))
    kd = kd.groupby(kd.index.floor("D")).last().pct_change()
    print(f"\nErgänzungs-Prüfung: 80 % Kombi + 20 % Kandidat (Kombi allein: gesichert {base['secured']:+.1%}, "
          f"Rückgang 90 % {base['boot']['dd_p90']:.0%})")
    for fam in F.ROUND2B:
        cand = np.load(out / f"oos_{fam}.npy")
        mix = comb([kombi, cand], [0.8, 0.2])
        ev = lab.evaluate(mix, t_oos, ew_daily, n_trials=n_all, sr_var=sr_var_pooled)
        cd = pd.Series(cand, index=pd.to_datetime(t_oos, unit="ms"))
        cd = cd.groupby(cd.index.floor("D")).last().pct_change()
        corr = float(kd.corr(cd))
        stress = report["families"][fam]["oos_stress"]["cagr"]
        ok = ev["secured"] > base["secured"] and ev["boot"]["dd_p90"] <= base["boot"]["dd_p90"] + 1e-9 and stress > 0
        report["blend_2b"][fam] = dict(cagr=ev["cagr"], maxdd=ev["maxdd"], secured=ev["secured"],
                                       dd_p90=ev["boot"]["dd_p90"], corr_kombi=corr, stress_candidate=stress, passes=ok)
        print(f"  {fam:<10} Mischung {ev['cagr']:+7.1%}/Jahr, DD {ev['maxdd']:4.0%}, gesichert {ev['secured']:+7.1%}, "
              f"DD90 {ev['boot']['dd_p90']:4.0%} | Korrelation zur Kombi {corr:+.2f} | Härtetest Kandidat {stress:+.1%} | "
              f"{'BESTANDEN' if ok else 'nicht bestanden'}", flush=True)
    report["meta"]["trials_total"] = n_all
    report["meta"]["sr_var_all"] = sr_var_all
    report["meta"]["sr_var_pooled"] = sr_var_pooled
    report["meta"]["family_sr_var"] = fam_var
    (out / "results.json").write_text(json.dumps(report, indent=1, default=float), encoding="utf-8")
    print("\nFertig:", out / "results.json")


if __name__ == "__main__":
    main()
