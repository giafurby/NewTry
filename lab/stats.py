"""
Der gemeinsame Maßstab: Kennzahlen, Unsicherheit, Mehrfachtest-Korrektur, Markt-Abgleich.

Alle Kandidaten werden mit GENAU diesen Funktionen bewertet (siehe MASSSTAB.md):
  * metrics()      Netto-Wachstum, größter Rückgang innerhalb des Tages, Monats-/Jahresprofil, CVaR
  * bootstrap()    Block-Bootstrap der Tagesrenditen: wie sicher ist das Wachstum, wie tief kann es fallen?
  * deflated_sharpe()  Bailey & López de Prado: Ist das beste von n Ergebnissen mehr als Glück?
  * alpha_vs()     Verdienst gegen den Markt (gleichgewichtet gehaltene Coins): echte Fähigkeit oder nur Marktrisiko?
  * random_entry_test()  azubiassist-Zufallsvergleich: Ist der Einstieg besser als zufällige Zeitpunkte?
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pandas as pd
from numba import njit

_N = NormalDist()
DAY = 86_400_000


def daily(eq: np.ndarray, T: np.ndarray, start: int, end: int) -> pd.Series:
    """Kapital am Ende jedes UTC-Tages (letzte bewertete 15m-Kerze)."""
    s = pd.Series(eq[start:end], index=pd.to_datetime(T[start:end], unit="ms"))
    s = s.dropna()
    return s.groupby(s.index.floor("D")).last()


def metrics(eq: np.ndarray, T: np.ndarray, start: int, end: int) -> dict:
    seg = eq[start:end]
    ok = np.isfinite(seg)
    seg = seg[ok]
    d = daily(eq, T, start, end)
    years = (T[end - 1] - T[start]) / (365.25 * DAY)
    growth = math.log(seg[-1] / seg[0]) / years
    peak = np.maximum.accumulate(seg)
    dd = float((1 - seg / peak).max())
    r = d.pct_change().dropna()
    lr = np.log1p(r)
    vol = float(r.std() * math.sqrt(365))
    sharpe = float(r.mean() / r.std() * math.sqrt(365)) if r.std() > 0 else 0.0
    down = r[r < 0]
    sortino = float(r.mean() / math.sqrt((down ** 2).mean()) * math.sqrt(365)) if len(down) else 0.0
    monthly = d.resample("ME").last().pct_change().dropna()
    first_month = d.resample("ME").last().iloc[0] / d.iloc[0] - 1 if len(d) else 0.0
    monthly = pd.concat([pd.Series([first_month], index=[d.resample("ME").last().index[0]]), monthly])
    ys = d.groupby(d.index.year)
    yearly = pd.Series({y: g.iloc[-1] / (d[d.index < g.index[0]].iloc[-1] if (d.index < g.index[0]).any() else g.iloc[0]) - 1
                        for y, g in ys})
    q = np.quantile(r, 0.05) if len(r) else 0.0
    cvar = float(r[r <= q].mean()) if len(r) else 0.0
    # Zeit unter Wasser (längste Phase ohne neuen Höchststand, in Tagen)
    under = (d < d.cummax()).astype(int)
    longest = int(under.groupby((under == 0).cumsum()).sum().max()) if len(under) else 0
    return dict(growth=growth, cagr=math.exp(growth) - 1, maxdd=dd, vol=vol, sharpe=sharpe, sortino=sortino,
                calmar=(math.exp(growth) - 1) / dd if dd > 0 else float("inf"), cvar95_day=cvar,
                worst_month=float(monthly.min()), neg_months=float((monthly < 0).mean()), months=len(monthly),
                yearly={int(k): float(v) for k, v in yearly.items()}, worst_year=float(yearly.min()),
                neg_years=int((yearly < 0).sum()), underwater_days=longest, days=len(d),
                skew=float(pd.Series(lr).skew()), kurt=float(pd.Series(lr).kurt() + 3.0),
                sr_daily=float(r.mean() / r.std()) if r.std() > 0 else 0.0)


def bootstrap(daily_returns: np.ndarray, n: int = 2000, block: int = 20, seed: int = 7) -> dict:
    """Stationärer Block-Bootstrap (Politis-Romano, mittlere Blocklänge `block` Tage). Liefert Verteilungen von
    jährlichem log-Wachstum und größtem Rückgang (auf Tagesbasis)."""
    r = np.asarray(daily_returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    g, d = _boot(np.log1p(r), n, block, seed)
    return dict(growth_p10=float(np.quantile(g, 0.10)), growth_p50=float(np.quantile(g, 0.50)),
                growth_p90=float(np.quantile(g, 0.90)), p_positive=float((g > 0).mean()),
                dd_p50=float(np.quantile(d, 0.50)), dd_p90=float(np.quantile(d, 0.90)), p_dd_over_50=float((d > 0.5).mean()))


@njit(cache=True)
def _boot(lr, n, block, seed):
    np.random.seed(seed)
    T = len(lr)
    g = np.empty(n)
    d = np.empty(n)
    p = 1.0 / block
    for k in range(n):
        idx = np.random.randint(T)
        s = 0.0
        peak = 0.0
        mdd = 0.0
        for t in range(T):
            if t > 0:
                if np.random.random() < p:
                    idx = np.random.randint(T)
                else:
                    idx = (idx + 1) % T
            s += lr[idx]
            if s > peak:
                peak = s
            dd = 1.0 - math.exp(s - peak)
            if dd > mdd:
                mdd = dd
        g[k] = s / T * 365.0
        d[k] = mdd
    return g, d


def deflated_sharpe(sr: float, n_obs: int, skew: float, kurt: float, n_trials: int, sr_var: float) -> float:
    """Wahrscheinlichkeit, dass die wahre Sharpe-Ratio > 0 ist, nachdem das beste von n_trials Ergebnissen gewählt wurde.
    sr, sr_var in Tages-Einheiten. >= 0,95 gilt als belastbar."""
    if n_obs < 3:
        return 0.0
    n = max(1, int(n_trials))
    if n == 1:
        sr0 = 0.0
    else:
        g = 0.5772156649
        sr0 = math.sqrt(max(sr_var, 1e-12)) * ((1 - g) * _N.inv_cdf(1 - 1 / n) + g * _N.inv_cdf(1 - 1 / (n * math.e)))
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr * sr))
    return float(_N.cdf((sr - sr0) * math.sqrt(n_obs - 1) / denom))


def newey_west_t(y: np.ndarray, X: np.ndarray, lags: int = 5) -> tuple[np.ndarray, np.ndarray]:
    """OLS-Koeffizienten und t-Werte mit Newey-West-Standardfehlern."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ beta
    XtX_inv = np.linalg.inv(X.T @ X)
    S = (X * e[:, None]).T @ (X * e[:, None])
    for L in range(1, lags + 1):
        w = 1 - L / (lags + 1)
        G = (X[L:] * e[L:, None]).T @ (X[:-L] * e[:-L, None])
        S += w * (G + G.T)
    cov = XtX_inv @ S @ XtX_inv
    return beta, beta / np.sqrt(np.diag(cov))


def alpha_vs(strategy_daily: pd.Series, market_daily: pd.Series) -> dict:
    """Tagesrenditen der Strategie = alpha + beta × Markt. alpha in % pro Jahr, t mit Newey-West (5 Tage)."""
    a = strategy_daily.pct_change()
    b = market_daily.pct_change()
    df = pd.concat([a, b], axis=1, join="inner").dropna()
    if len(df) < 60:
        return dict(alpha=0.0, alpha_t=0.0, beta=0.0)
    X = np.column_stack([np.ones(len(df)), df.iloc[:, 1].to_numpy()])
    coef, t = newey_west_t(df.iloc[:, 0].to_numpy(), X)
    return dict(alpha=float(coef[0] * 365), alpha_t=float(t[0]), beta=float(coef[1]))


# ------------------------------------------------------------------ Zufallsvergleich (aus azubiassist übernommen)
@njit(cache=True)
def _trade(O, H, L, CF, EP, i, j, stopf, tgtf, trailf, hold, cost, N):
    ep = EP[i + 1, j]
    if ep != ep:
        return np.nan, i + 1
    stop = ep * (1 - stopf) if stopf == stopf else -1.0
    tgt = ep * (1 + tgtf)
    peak = ep
    end = min(N - 1, i + hold)
    for k in range(i + 1, end + 1):
        lo = L[k, j]
        if lo == lo:
            first = k == i + 1
            if lo <= stop:
                px = stop if first else min(stop, O[k, j])
                return px / ep * (1 - cost) ** 2 - 1, k
            if H[k, j] >= tgt:
                px = tgt if first else max(tgt, O[k, j])
                return px / ep * (1 - cost) ** 2 - 1, k
            if H[k, j] > peak:
                peak = H[k, j]
                if trailf > 0 and peak * (1 - trailf) > stop:
                    stop = peak * (1 - trailf)
    c = CF[end, j]
    return c / ep * (1 - cost) ** 2 - 1, end


@njit(cache=True)
def _real(O, H, L, CF, EP, sig, stopf, tgtf, trailf, hold, cost, start, end):
    N, K = O.shape
    out = np.full(N * 0 + 200_000, np.nan)
    coin = np.zeros(200_000, np.int64)
    n = 0
    for j in range(K):
        i = start
        while i < end - 1:
            if sig[i, j]:
                r, k = _trade(O, H, L, CF, EP, i, j, stopf[i, j], tgtf[i, j], trailf[i, j], hold, cost, N)
                if r == r and n < 200_000:
                    out[n] = r
                    coin[n] = j
                    n += 1
                i = k + 1
            else:
                i += 1
    return out[:n], coin[:n]


@njit(cache=True)
def _random(O, H, L, CF, EP, live, counts, stopf, tgtf, trailf, hold, cost, start, end, iters, seed):
    np.random.seed(seed)
    N, K = O.shape
    means = np.empty(iters)
    for it in range(iters):
        s = 0.0
        n = 0
        for j in range(K):
            c = counts[j]
            if c == 0:
                continue
            got = 0
            tries = 0
            while got < c and tries < c * 50:
                tries += 1
                i = start + np.random.randint(end - 1 - start)
                if not live[i, j] or not (stopf[i, j] == stopf[i, j] or hold > 0):
                    continue
                sf = stopf[i, j]
                if sf != sf:
                    continue
                r, k = _trade(O, H, L, CF, EP, i, j, sf, tgtf[i, j], trailf[i, j], hold, cost, N)
                if r == r:
                    s += r
                    n += 1
                    got += 1
        means[it] = s / n if n else 0.0
    return means


def random_entry_test(m, sig, stopf, tgtf, trailf, hold, cost, start, end, iters=300, seed=20260101) -> dict:
    """Einseitiger Permutationstest: gleich viele Einstiege je Coin zu zufälligen Zeitpunkten, gleiche Ausstiege/Kosten.
    Stop/Ziel werden an der Zufallskerze aus denselben Kennzahlen berechnet (z. B. ATR)."""
    real, coin = _real(m.O, m.H, m.L, m.CF, m.EP, sig, stopf, tgtf, trailf, hold, cost, start, end)
    counts = np.bincount(coin, minlength=m.K).astype(np.int64)
    rnd = _random(m.O, m.H, m.L, m.CF, m.EP, m.live, counts, stopf, tgtf, trailf, hold, cost, start, end, iters, seed)
    mean = float(real.mean()) if len(real) else 0.0
    return dict(trades=int(len(real)), mean=mean, random_mean=float(rnd.mean()), random_p95=float(np.quantile(rnd, 0.95)),
                p=float((1 + (rnd >= mean).sum()) / (1 + iters)),
                t=float(mean / (real.std(ddof=1) / math.sqrt(len(real)))) if len(real) > 2 else 0.0)
