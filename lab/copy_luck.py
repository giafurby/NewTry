"""
Copy-Trading-Ranglisten: Wie viel von „+34 % in 30 Tagen bei 7,6 % Rückgang“ ist Können, wie viel Glück?

Simuliert Händler OHNE jedes Können auf echten Binance-Kursen (10 Coins): Sie kaufen zufällige Coins zu zufälligen
Zeitpunkten und halten zufällig lange – jeder mit eigenem Stil (1–5 Positionen gleichzeitig, Haltedauer im Mittel
4 Stunden bis 10 Tage, manche mit Gewinnziel und Stop). Kosten 0,10 % je Seite (Binance ohne BNB), gekauft und verkauft
zum Stundenschluss ohne Verzögerung und ohne Schlupf – günstiger, als es echte Händler und erst recht Kopierer haben.

Dann wie in der Binance-App „Spot Copy → High ROI“: Rangliste nach 30-Tage-Rendite (ROI) mit 30-Tage-Rückgang (MDD) in
jedem Monat seit 2020, und die Frage: Was machen die Spitzenreiter im Folgemonat? Und: Was hätte jemand verdient, der
jeden Monat den Spitzenreiter des Vormonats kopiert (abzüglich 10 % Gewinnbeteiligung für den Trader)?

Aufruf: python -I lab/copy_luck.py <cache15> [Anzahl Händler]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from numba import njit  # noqa: E402

from data import load_market  # noqa: E402

COST = 0.001          # Binance-Gebühr je Seite ohne BNB-Rabatt
STEP = 4              # Stundentakt auf dem 15m-Raster
WINDOW = 30 * 24      # 30 Tage in Stunden
SHARE = 0.10          # Gewinnbeteiligung des Traders beim Kopieren (Binance Spot Copy)


@njit(cache=True)
def _simulate(CF, start, step, n_steps, window, n, seed, cost):
    """Gibt Kapital an den Fenstergrenzen (n, W+1) und größten Rückgang je Fenster (n, W) zurück."""
    K = CF.shape[1]
    W = n_steps // window
    eqb = np.empty((n, W + 1))
    mdd = np.zeros((n, W))
    style = np.empty((n, 5))
    tps = np.array([0.0, 0.0, 0.03, 0.05, 0.10, 0.20, 0.50])
    sls = np.array([0.0, 0.0, 0.03, 0.05, 0.10, 0.20])
    np.random.seed(seed)
    for t in range(n):
        P = 1 + np.random.randint(5)
        hold = np.exp(np.log(4.0) + np.random.random() * (np.log(240.0) - np.log(4.0)))
        p_in = np.exp(np.log(1.0 / 72.0) + np.random.random() * (np.log(0.5) - np.log(1.0 / 72.0)))
        tp = tps[np.random.randint(len(tps))]
        sl = sls[np.random.randint(len(sls))]
        style[t, 0], style[t, 1], style[t, 2], style[t, 3], style[t, 4] = P, hold, p_in, tp, sl
        cash = 1.0
        coin = np.full(P, -1)
        units = np.zeros(P)
        entry = np.zeros(P)
        left = np.zeros(P)
        peak = 1.0
        w = 0
        eqb[t, 0] = 1.0
        for s in range(n_steps):
            i = start + s * step
            # Ausstiege: Zeit abgelaufen, Gewinnziel oder Stop (zum Stundenschluss)
            for p in range(P):
                if coin[p] >= 0:
                    px = CF[i, coin[p]]
                    left[p] -= 1.0
                    r = px / entry[p] - 1.0
                    if left[p] <= 0.0 or (tp > 0.0 and r >= tp) or (sl > 0.0 and r <= -sl):
                        cash += units[p] * px * (1.0 - cost)
                        coin[p] = -1
                        units[p] = 0.0
            val = cash
            for p in range(P):
                if coin[p] >= 0:
                    val += units[p] * CF[i, coin[p]]
            # Einstiege: freier Platz, Zufall entscheidet über Zeitpunkt, Coin und Haltedauer
            for p in range(P):
                if coin[p] < 0 and np.random.random() < p_in:
                    j = np.random.randint(K)
                    px = CF[i, j]
                    if not np.isfinite(px):
                        continue
                    taken = False
                    for q in range(P):
                        if coin[q] == j:
                            taken = True
                    if taken:
                        continue
                    amount = min(cash, val / P)
                    if amount < 0.01 * val:
                        continue
                    cash -= amount
                    units[p] = amount * (1.0 - cost) / px
                    entry[p] = px
                    coin[p] = j
                    left[p] = max(1.0, np.floor(np.random.exponential(hold) + 0.5))
            eq = cash
            for p in range(P):
                if coin[p] >= 0:
                    eq += units[p] * CF[i, coin[p]]
            if eq > peak:
                peak = eq
            dd = 1.0 - eq / peak
            if dd > mdd[t, w]:
                mdd[t, w] = dd
            if (s + 1) % window == 0:
                w += 1
                eqb[t, w] = eq
                peak = eq
                if w == W:
                    break
    return eqb, mdd, style


def spearman(a, b):
    ra, rb = pd.Series(a).rank().to_numpy(), pd.Series(b).rank().to_numpy()
    return float(np.corrcoef(ra, rb)[0, 1])


def main():
    m = load_market(sys.argv[1])
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
    s0 = m.index_of("2020-01-01")
    n_steps = (m.N - 1 - s0) // STEP
    eqb, mdd, style = _simulate(m.CF, s0, STEP, n_steps, WINDOW, n, 20261112, COST)
    W = mdd.shape[1]
    roi = eqb[:, 1:] / eqb[:, :-1] - 1.0
    t_start = [pd.Timestamp(int(m.T[s0 + w * WINDOW * STEP]), unit="ms") for w in range(W)]

    # Markt zum Vergleich: alle 10 Coins zu gleichen Teilen halten
    mkt = []
    for w in range(W):
        a, b = s0 + w * WINDOW * STEP, s0 + (w + 1) * WINDOW * STEP
        ok = np.isfinite(m.CF[a]) & np.isfinite(m.CF[b])
        mkt.append(float(np.mean(m.CF[b, ok] / m.CF[a, ok]) - 1.0))
    mkt = np.array(mkt)

    print(f"{n} Händler ohne Können, {W} Monate (30-Tage-Fenster) {t_start[0]:%m/%Y}–{t_start[-1]:%m/%Y}, "
          f"Kosten {COST:.2%} je Seite\n")
    rows = []
    for w in range(W):
        r, d = roi[:, w], mdd[:, w]
        low = d <= 0.08
        best = int(np.argmax(r))
        best_low = int(np.argmax(np.where(low, r, -np.inf))) if low.any() else -1
        like_cp = int(np.sum((r >= 0.30) & (d <= 0.0756)))      # wie „Compound Power“: ≥ +30 % bei ≤ 7,56 %
        like_ce = int(np.sum((r >= 0.1876) & (d <= 0.053)))     # wie „cata-E“: ≥ +18,76 % bei ≤ 5,30 %
        row = dict(start=t_start[w], market=mkt[w], best=r[best], best_mdd=d[best],
                   best_low=r[best_low] if best_low >= 0 else np.nan, like_cp=like_cp, like_ce=like_ce,
                   median=float(np.median(r)), share_pos=float(np.mean(r > 0)))
        if w + 1 < W:
            top = np.argsort(-r)[:10]
            # Rangliste wie in der App: hohe Rendite UND kleiner Rückgang (MDD ≤ 10 %)
            eligible = np.flatnonzero(d <= 0.10)
            top_low = eligible[np.argsort(-r[eligible])[:10]] if len(eligible) else top
            nxt = roi[:, w + 1]
            row.update(top10_next=float(np.mean(nxt[top])), top10low_next=float(np.mean(nxt[top_low])),
                       all_next=float(np.mean(nxt)), bottom10_next=float(np.mean(nxt[np.argsort(r)[:10]])),
                       rho=spearman(r, nxt), copy_next=float(nxt[top_low[0]]))
        rows.append(row)
    df = pd.DataFrame(rows)

    def block(sel, label):
        d = df[sel]
        dn = d.dropna(subset=["top10_next"])
        print(f"— {label}: {len(d)} Monate")
        print(f"  Bester Zufallshändler je Monat: Median {d.best.median():+.0%}, in {np.mean(d.best >= 0.30):.0%} der Monate "
              f"≥ +30 %")
        print(f"  Monate mit mindestens einem „Compound Power“ (≥ +30 % bei ≤ 7,6 % Rückgang): "
              f"{np.mean(d.like_cp > 0):.0%} (im Schnitt {d.like_cp.mean():.1f} von {n} Händlern)")
        print(f"  Monate mit mindestens einem „cata-E“ (≥ +18,8 % bei ≤ 5,3 % Rückgang): {np.mean(d.like_ce > 0):.0%} "
              f"(im Schnitt {d.like_ce.mean():.1f} von {n})")
        print(f"  Folgemonat: Top-10 nach ROI {dn.top10_next.mean():+.2%}, Top-10 mit MDD ≤ 10 % "
              f"{dn.top10low_next.mean():+.2%}, alle {dn.all_next.mean():+.2%}, schlechteste 10 {dn.bottom10_next.mean():+.2%}, "
              f"Markt {d.market.mean():+.2%} je Monat")
        print(f"  Rangkorrelation ROI Monat → Folgemonat: Mittel {dn.rho.mean():+.3f} "
              f"(0 = Rangliste sagt nichts voraus; 1 = Rangliste bleibt gleich)")
        # Spitzenreiter jeden Monat kopieren (10 % Gewinnbeteiligung auf Gewinnmonate)
        c = dn.copy_next.to_numpy()
        net = np.where(c > 0, c * (1.0 - SHARE), c)
        years = len(net) * 30 / 365.25
        growth = float(np.prod(1.0 + net))
        avg = float(np.prod(1.0 + dn.all_next.to_numpy()))
        mk = float(np.prod(1.0 + d.market.to_numpy()[1:len(net) + 1]))
        print(f"  Jeden Monat den Spitzenreiter (MDD ≤ 10 %) des Vormonats kopieren: {growth ** (1 / years) - 1:+.1%}/Jahr "
              f"(Durchschnittshändler {avg ** (1 / years) - 1:+.1%}/Jahr, Markt halten {mk ** (1 / years) - 1:+.1%}/Jahr), "
              f"schlechtester Monat {net.min():+.0%}")
        print()

    block(df.start >= pd.Timestamp("2020-01-01"), "2020–10/2026")
    block(df.start >= pd.Timestamp("2025-01-01"), "seit 2025")

    print("Monate mit dem höchsten Spitzenreiter (Zufall!) und was die Top-10 (MDD ≤ 10 %) im Folgemonat machten:")
    for _, r in df.sort_values("best", ascending=False).head(8).iterrows():
        nx = "" if pd.isna(r.get("top10low_next")) else f"→ Folgemonat {r.top10low_next:+.0%} (alle {r.all_next:+.0%})"
        print(f"  ab {r.start:%d.%m.%Y}: bester {r.best:+.0%} (Rückgang {r.best_mdd:.0%}), bester mit ≤ 8 % Rückgang "
              f"{r.best_low:+.0%}, Markt {r.market:+.0%} {nx}")
    print("\nLetzte 6 Monate:")
    for _, r in df.tail(6).iterrows():
        nx = "" if pd.isna(r.get("top10low_next")) else f"→ Folgemonat Top-10 {r.top10low_next:+.0%} (alle {r.all_next:+.0%})"
        print(f"  ab {r.start:%d.%m.%Y}: bester {r.best:+.0%}, bester mit ≤ 8 % Rückgang {r.best_low:+.0%}, "
              f"„Compound Power“-artige {r.like_cp}, Markt {r.market:+.0%} {nx}")


if __name__ == "__main__":
    main()
