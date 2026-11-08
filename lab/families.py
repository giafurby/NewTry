"""
Strategiefamilien. Jede Familie hat ein Parameter-Raster (`grid`) und eine Funktion `run(ctx, p, cost, start, end)`,
die mit der gemeinsamen Maschine (engine.py) eine Kapitalkurve auf der 15m-Achse liefert.

Familie          Herkunft      Idee
TREND4H          NewTry        4h-Schluss über dem N-Kerzen-Hoch und über EMA 200, Stop/Ziel in ATR, 1 % Risiko
CRASH            NewTry        Einbruch um x % in m Kerzen kaufen, nach h Kerzen verkaufen, Notstop, Sperre nach Stop
TSMOM            neu           Zeitreihen-Momentum je Coin (mehrere Rückblicke), Gewicht nach Schwankung, täglich
XSMOM            neu           die k stärksten Coins (Rendite über L Tage), optional nur wenn BTC im Aufwärtstrend
CORE             neu           nur BTC (und ETH): halten, solange der Tagesschluss über dem Durchschnitt liegt
PULLBACK         Gemini A      Rücksetzer im Aufwärtstrend (1h-RSI, Bollinger-Mitte, grüne Umkehrkerze), Teilverkauf, Trailing
TRANCHE          Gemini B      gestaffelter Rücksetzer-Kauf in 3 Tranchen im Seitwärts-Regime, schneller Gewinnausstieg
HOLD_*           Maßstab       Cash, BTC halten, alle Coins gleich gewichtet halten
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from data import Bars, Market, aggregate
import engine

BARS_4H = 16
BARS_1H = 4
BARS_1D = 96


# ====================================================================== Kennzahlen (auf (B, K)-Feldern)
def _df(x):
    return pd.DataFrame(x)


def ema(x, n):
    return _df(x).ffill().ewm(span=n, adjust=False, min_periods=n).mean().to_numpy()


def sma(x, n):
    return _df(x).ffill().rolling(n, min_periods=n).mean().to_numpy()


def rolling_max_prior(x, n):
    """Hoch der vorherigen n Kerzen; einzelne fehlende Kerzen (Börsenwartung) blockieren das Signal nicht."""
    return _df(x).shift(1).rolling(n, min_periods=int(n * 0.9)).max().to_numpy()


def atr(b: Bars, n=14):
    c = _df(b.c).ffill()
    pc = c.shift(1)
    h, l = _df(b.h), _df(b.l)
    tr = np.maximum(np.maximum((h - l).to_numpy(), (h - pc).abs().to_numpy()), (l - pc).abs().to_numpy())
    return _df(tr).ewm(alpha=1 / n, adjust=False, min_periods=n).mean().to_numpy()


def rsi(c, n=14):
    c = _df(c).ffill()
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d).clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return (100 - 100 / (1 + up / dn)).to_numpy()


def adx(b: Bars, n=14):
    h, l = _df(b.h).ffill(), _df(b.l).ffill()
    up, dn = h.diff(), -l.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = atr(b, n)
    pdi = 100 * _df(pdm).ewm(alpha=1 / n, adjust=False, min_periods=n).mean().to_numpy() / a
    ndi = 100 * _df(ndm).ewm(alpha=1 / n, adjust=False, min_periods=n).mean().to_numpy() / a
    dx = 100 * np.abs(pdi - ndi) / np.where(pdi + ndi > 0, pdi + ndi, np.nan)
    return _df(dx).ewm(alpha=1 / n, adjust=False, min_periods=n).mean().to_numpy()


# ====================================================================== Kontext (zwischengespeicherte Zeitebenen)
@dataclass
class Ctx:
    m: Market
    cache: dict = field(default_factory=dict)

    def bars(self, minutes: int) -> Bars:
        key = ("bars", minutes)
        if key not in self.cache:
            self.cache[key] = aggregate(self.m, minutes)
        return self.cache[key]

    def memo(self, key, fn):
        if key not in self.cache:
            self.cache[key] = fn()
        return self.cache[key]


def on_grid(m: Market, b: Bars, values, dtype=np.float64):
    """Wert der höheren Zeitebene am Schluss der Kerze (nur dort, sonst NaN/False)."""
    out = np.zeros((m.N, m.K), bool) if dtype == bool else np.full((m.N, m.K), np.nan)
    for j in range(m.K):
        ok = b.end[:, j] >= 0
        out[b.end[ok, j], j] = values[ok, j]
    return out


def held(m: Market, b: Bars, values):
    """Wert der höheren Zeitebene, gültig ab ihrem Schluss bis zum nächsten Schluss (vorwärts aufgefüllt)."""
    g = on_grid(m, b, values.astype(np.float64))
    return pd.DataFrame(g).ffill().to_numpy()


def _no(m):
    return np.zeros((m.N, m.K), bool)


def _const(m, v):
    return np.full((m.N, m.K), v, dtype=np.float64)


def _trades(ctx, sig, prio, stopf, tgtf, trailf, hold, size_mode, size_a, size_cap, kmax, cost, start, end,
            cooldown=0, min_frac=0.02, part_frac=0.0, part_tgt=0.0, exit_sig=None, extend=False):
    m = ctx.m
    eq, tr = engine.sim_trades(m.O, m.H, m.L, m.CF, m.EP, sig, prio, stopf, tgtf, trailf, int(hold), float(part_frac),
                               float(part_tgt), int(size_mode), float(size_a), float(size_cap), int(kmax), float(cost),
                               int(cooldown), int(start), int(end), float(min_frac),
                               _no(m) if exit_sig is None else exit_sig, bool(extend))
    return eq, tr


# ====================================================================== TREND4H (NewTry, Regel 1)
def trend_signals(ctx, n, sl, tp):
    def make():
        m, b = ctx.m, ctx.bars(240)
        c = b.c
        prior = rolling_max_prior(b.h, n)
        e200 = ctx.memo(("ema4h", 200), lambda: ema(c, 200))
        a = ctx.memo(("atr4h", 14), lambda: atr(b, 14))
        with np.errstate(invalid="ignore", divide="ignore"):
            af = a / c
            stopf = np.maximum(sl * af, 0.002)
            sig = (c > prior) & (c >= e200) & (stopf <= 0.10)
            tgtf = np.maximum(tp * af, stopf * 1.5)
        return on_grid(m, b, sig, bool), on_grid(m, b, stopf), on_grid(m, b, tgtf)
    return ctx.memo(("trend", n, sl, tp), make)


TREND_GRID = [dict(n=n, sl=sl, tp=tp, mb=mb) for n, sl, tp, mb in
              itertools.product((50, 100, 200), (1.5, 2.0, 3.0), (8.0, 15.0, 1000.0), (60, 120, 240))]
TREND_NEWTRY = dict(n=100, sl=2.0, tp=15.0, mb=120)


def run_trend(ctx, p, cost, start, end, risk=0.01, cap=0.33, kmax=3):
    m = ctx.m
    sig, stopf, tgtf = trend_signals(ctx, p["n"], p["sl"], p["tp"])
    eq, tr = _trades(ctx, sig, np.zeros((m.N, m.K)), stopf, tgtf, _const(m, 0.0), p["mb"] * BARS_4H, 1,
                     p.get("risk", risk), p.get("cap", cap), p.get("kmax", kmax), cost, start, end)
    return eq, tr


# ====================================================================== CRASH (NewTry, Regel 2)
def crash_signals(ctx, x, lb):
    def make():
        m = ctx.m
        C = m.C
        prev = np.vstack([np.full((lb, m.K), np.nan), C[:-lb]])
        with np.errstate(invalid="ignore", divide="ignore"):
            chg = C / prev - 1
        gap = np.zeros((m.N, m.K), bool)
        for k in range(lb + 1):
            gap |= np.vstack([np.zeros((k, m.K), bool), ~m.live[: m.N - k]])
        sig = m.live & ~gap & (chg <= -x)
        return sig, np.nan_to_num(-chg)
    return ctx.memo(("crash", x, lb), make)


CRASH_GRID = [dict(x=x, lb=lb, h=h, s=s) for x, lb, h, s in
              itertools.product((0.06, 0.08, 0.09, 0.10, 0.12, 0.15), (4, 16, 48), (4, 8, 16, 32, 96), (0.10, 0.15, 0.20))]
CRASH_NEWTRY = dict(x=0.09, lb=16, h=16, s=0.15)


def run_crash(ctx, p, cost, start, end, size=0.20, kmax=3, cooldown=96):
    m = ctx.m
    sig, prio = crash_signals(ctx, p["x"], p["lb"])
    if not p.get("deepest_first", False):          # wie der Bot: feste Coin-Reihenfolge
        prio = np.zeros_like(prio)
    eq, tr = _trades(ctx, sig, prio, _const(m, p["s"]), _const(m, np.inf), _const(m, 0.0), p["h"], 0,
                     p.get("size", size), p.get("size", size), p.get("kmax", kmax), cost, start, end,
                     cooldown=p.get("cooldown", cooldown), min_frac=p.get("size", size) * 0.5)
    return eq, tr


# ====================================================================== gemeinsame Hilfen für Gewichts-Strategien
def daily_ctx(ctx):
    def make():
        b = ctx.bars(1440)
        c = pd.DataFrame(b.c).ffill()
        lr = np.log(c).diff()
        vol = lr.rolling(30, min_periods=20).std().to_numpy() * np.sqrt(365)
        ends = b.end.max(axis=1)                      # Tagesschluss (letzte vorhandene 15m-Kerze des Tages)
        ok = ends >= 0
        return dict(b=b, c=c.to_numpy(), vol=vol, ends=ends, ok=ok, live=np.isfinite(b.c))
    return ctx.memo("daily", make)


def _weights_run(ctx, W, days, cost, start, end, band=0.02):
    m = ctx.m
    d = daily_ctx(ctx)
    rebal = d["ends"][days]
    keep = rebal >= 0
    eq, turnover, orders = engine.sim_weights(m.CF, m.EP, W[days][keep], rebal[keep].astype(np.int64), float(cost),
                                              float(band), int(start), int(end))
    return eq, dict(turnover=turnover, orders=orders)


def _rebal_days(d, every):
    idx = np.flatnonzero(d["ok"])
    if every == 1:
        return idx
    t = pd.to_datetime(d["b"].t[idx], unit="ms")
    return idx[t.dayofweek == 6]        # Sonntag-Schluss -> Montag 00:01 handeln


# ====================================================================== TSMOM (neu)
TSMOM_GRID = [dict(lbs=lbs, tv=tv, every=e) for lbs, tv, e in
              itertools.product(((20,), (60,), (120,), (20, 60, 120), (10, 20, 40, 80, 160)), (0.5, 0.8, 1.2), (1, 7))]


def run_tsmom(ctx, p, cost, start, end):
    d = daily_ctx(ctx)
    c, vol, live = d["c"], d["vol"], d["live"]
    sigs = []
    for L in p["lbs"]:
        with np.errstate(invalid="ignore", divide="ignore"):
            sigs.append((c / pd.DataFrame(c).shift(L).to_numpy() - 1 > 0).astype(float))
    s = np.mean(sigs, axis=0)
    n_live = np.maximum(live.sum(axis=1, keepdims=True), 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        w = s * np.minimum(p["tv"] / vol, 2.0) / n_live
    w = np.where(live & np.isfinite(w), w, 0.0)
    tot = w.sum(axis=1, keepdims=True)
    w = np.where(tot > 1, w / tot, w)
    eq, info = _weights_run(ctx, w, _rebal_days(d, p["every"]), cost, start, end)
    return eq, info


# ====================================================================== XSMOM (neu)
XSMOM_GRID = [dict(L=L, k=k, regime=r, tv=tv) for L, k, r, tv in
              itertools.product((14, 30, 60, 90), (2, 3, 5), (0, 100), (0.0, 0.8))]


def run_xsmom(ctx, p, cost, start, end):
    d = daily_ctx(ctx)
    c, vol, live = d["c"], d["vol"], d["live"]
    with np.errstate(invalid="ignore", divide="ignore"):
        mom = c / pd.DataFrame(c).shift(p["L"]).to_numpy() - 1
    mom = np.where(live & np.isfinite(mom), mom, -np.inf)
    rank = (-mom).argsort(axis=1).argsort(axis=1)
    pick = (rank < p["k"]) & (mom > 0)
    w = pick / p["k"]
    if p["tv"] > 0:
        with np.errstate(invalid="ignore", divide="ignore"):
            w = w * np.nan_to_num(np.minimum(1.0, p["tv"] / vol))
    if p["regime"]:
        btc = c[:, 0]
        ok = btc > pd.Series(btc).rolling(p["regime"], min_periods=p["regime"]).mean().to_numpy()
        w = w * ok[:, None]
    eq, info = _weights_run(ctx, w, _rebal_days(d, 7), cost, start, end)
    return eq, info


# ====================================================================== CORE (neu): BTC/ETH-Trend
CORE_GRID = [dict(L=L, tv=tv, coins=cs) for L, tv, cs in itertools.product((50, 100, 150, 200), (0.0, 0.6), (1, 2))]


def run_core(ctx, p, cost, start, end):
    d = daily_ctx(ctx)
    c, vol = d["c"], d["vol"]
    w = np.zeros_like(c)
    for j in range(p["coins"]):
        x = c[:, j]
        on = x > pd.Series(x).rolling(p["L"], min_periods=p["L"]).mean().to_numpy()
        wj = on / p["coins"]
        if p["tv"] > 0:
            with np.errstate(invalid="ignore", divide="ignore"):
                wj = wj * np.nan_to_num(np.minimum(1.0, p["tv"] / vol[:, j]))
        w[:, j] = wj
    eq, info = _weights_run(ctx, w, _rebal_days(d, 1), cost, start, end, band=0.05)
    return eq, info


# ====================================================================== Maßstäbe
def run_hold(ctx, p, cost, start, end):
    d = daily_ctx(ctx)
    live = d["live"]
    if p["what"] == "cash":
        return np.ones(ctx.m.N), {}
    if p["what"] == "btc":
        w = np.zeros(live.shape)
        w[:, 0] = 1.0
    else:
        w = live / np.maximum(live.sum(axis=1, keepdims=True), 1) * p.get("frac", 1.0)
    return _weights_run(ctx, w, _rebal_days(d, 7), cost, start, end, band=0.05)


# ====================================================================== PULLBACK (Gemini, Motor A)
def regime_bull(ctx):
    """4h: Schluss > EMA 200 und EMA 50 > EMA 200 (gilt ab dem 4h-Schluss)."""
    def make():
        b = ctx.bars(240)
        e50 = ema(b.c, 50)
        e200 = ctx.memo(("ema4h", 200), lambda: ema(b.c, 200))
        with np.errstate(invalid="ignore"):
            return held(ctx.m, b, ((b.c > e200) & (e50 > e200)).astype(float)) > 0.5
    return ctx.memo("bull", make)


def regime_range(ctx):
    """4h: Schluss < EMA 200 oder ADX(14) < 20."""
    def make():
        b = ctx.bars(240)
        e200 = ctx.memo(("ema4h", 200), lambda: ema(b.c, 200))
        with np.errstate(invalid="ignore"):
            r = (b.c < e200) | (adx(b, 14) < 20)
        return held(ctx.m, b, r.astype(float)) > 0.5
    return ctx.memo("range", make)


PULLBACK_GRID = [dict(th=th, pt=pt, tr=tr, hold=h) for th, pt, tr, h in
                 itertools.product((35.0, 42.0, 50.0), (0.015, 0.022, 0.03), (1.5, 2.5, 4.0), (7, 30))]
PULLBACK_GEMINI = dict(th=42.0, pt=0.022, tr=2.5, hold=7)


def run_pullback(ctx, p, cost, start, end, risk=0.01, cap=0.33, kmax=3):
    m = ctx.m

    def make():
        b = ctx.bars(60)
        c = pd.DataFrame(b.c).ffill().to_numpy()
        r = rsi(c, 14)
        mid = sma(c, 20)
        a = atr(b, 14)
        with np.errstate(invalid="ignore", divide="ignore"):
            prev_h = pd.DataFrame(b.h).shift(1).to_numpy()
            prev_setup_l = pd.DataFrame(b.l <= mid).shift(1).fillna(False).to_numpy(bool)
            trigger = (b.c > prev_h) & (b.c > b.o)
            af = a / b.c
        return dict(r_prev=pd.DataFrame(r).shift(1).to_numpy(), setup_l=prev_setup_l, trigger=trigger, af=af, b=b)
    f = ctx.memo("pullback_feat", make)
    with np.errstate(invalid="ignore"):
        sig1h = (f["r_prev"] < p["th"]) & f["setup_l"] & f["trigger"]
    sig = on_grid(m, f["b"], sig1h, bool) & regime_bull(ctx)
    trailf = on_grid(m, f["b"], np.clip(p["tr"] * f["af"], 0.004, 0.25))
    eq, tr = _trades(ctx, sig, np.zeros((m.N, m.K)), trailf, _const(m, np.inf), trailf, p["hold"] * BARS_1D, 1,
                     risk, cap, kmax, cost, start, end, part_frac=0.5, part_tgt=p["pt"])
    return eq, tr


# ====================================================================== TRANCHE (Gemini, Motor B)
TRANCHE_GRID = [dict(dev=dev, tp=tp, ema_exit=ee, regime=rg) for dev, tp, ee, rg in
                itertools.product((0.025, 0.03), (0.016, 0.022), (0, 1), (1, 0))]
TRANCHE_GEMINI = dict(dev=0.025, tp=0.022, ema_exit=1, regime=1)


def run_tranche(ctx, p, cost, start, end, pos_frac=0.30, kmax=3):
    m = ctx.m

    def make():
        b = ctx.bars(60)
        c = pd.DataFrame(b.c).ffill().to_numpy()
        r = rsi(c, 14)
        mid = sma(c, 20)
        e20 = ema(c, 20)
        vavg = pd.DataFrame(m.V).rolling(96, min_periods=48).mean().shift(1).to_numpy()
        with np.errstate(invalid="ignore"):
            vspike = m.V > 2.5 * vavg
            rev = m.C > m.O
        T = m.T
        stop_check = ((T + 900_000) % (4 * 3_600_000)) == 0
        return dict(b=b, c=c, r=r, mid=mid, e20=e20, vspike=vspike, rev=rev, stop_check=stop_check)
    f = ctx.memo("tranche_feat", make)
    with np.errstate(invalid="ignore"):
        s1 = (f["c"] <= f["mid"] * (1 - p["dev"])) & (f["r"] < 33)
        ex = f["c"] >= f["e20"]
    sig1 = on_grid(m, f["b"], s1, bool)
    if p["regime"]:
        sig1 &= regime_range(ctx)
    exit_sig = on_grid(m, f["b"], ex, bool) if p["ema_exit"] else _no(m)
    eq, tr = engine.sim_tranches(m.O, m.H, m.L, m.C, m.CF, m.EP, sig1, f["rev"], f["vspike"], 0.05, 0.08,
                                 np.array([0.30, 0.35, 0.35]), float(p["tp"]), 0.11, f["stop_check"], exit_sig,
                                 float(pos_frac), int(kmax), float(cost), int(start), int(end))
    return eq, tr


# ====================================================================== Runde 2b: Kandidaten aus der Gemini-Recherche
# Standardwerte und Raster genau wie im Gemini-Bericht vom 08.11.2026 (lab/ERGEBNISSE_V2B.md). Alles auf Tageskerzen
# (UTC), Entscheidung auf dem Tagesschluss, Ausführung 1 Minute danach – wie bei allen anderen Familien.
import warnings  # noqa: E402


def _days(ctx):
    b = ctx.bars(1440)
    t = pd.to_datetime(b.t, unit="ms")
    return b, t


LOWVOL_GRID = [dict(m=m_, d=d_, th=th) for m_, d_, th in
               itertools.product((14, 30, 60), (0.015, 0.03, 0.045), (-0.20, 0.0, 0.10))]
LOWVOL_GEMINI = dict(m=30, d=0.03, th=0.0)


def run_lowvol(ctx, p, cost, start, end):
    """Kandidat 1 (Bianchi et al. 2022): Tagesverlierer mit unterdurchschnittlichem Volumen kaufen, 1 Tag halten."""
    m = ctx.m
    b, _ = _days(ctx)

    def feats():
        c = b.c
        with np.errstate(invalid="ignore", divide="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            R = c / pd.DataFrame(c).shift(1).to_numpy() - 1
            rbar = np.nanmean(R, axis=1, keepdims=True)
            dv = c * b.v
            ldv = np.log(np.where(dv > 0, dv, np.nan))
        return R, rbar, ldv
    R, rbar, ldv = ctx.memo("lowvol_feat", feats)
    base = pd.DataFrame(ldv).shift(1).rolling(p["m"], min_periods=p["m"]).mean().to_numpy()
    with np.errstate(invalid="ignore"):
        sig = (R < rbar) & (R <= -p["d"]) & ((ldv - base) < p["th"])
    prio = on_grid(m, b, np.nan_to_num(-R))
    return _trades(ctx, on_grid(m, b, sig, bool), np.nan_to_num(prio), _const(m, 0.10), _const(m, np.inf),
                   _const(m, 0.0), BARS_1D, 0, 0.25, 0.25, 2, cost, start, end, min_frac=0.125, extend=True)


PASTLOSER_GRID = [dict(J=J, K=K, L=L) for J, K, L in itertools.product((4, 8, 12, 26), (1, 2, 4), (0.0, 0.10))]
PASTLOSER_GEMINI = dict(J=8, K=2, L=0.10)


def run_pastloser(ctx, p, cost, start, end):
    """Kandidat 2 (Dobrynskaya 2023): die 2 größten Verlierer über J Wochen kaufen, K Wochen halten (sonntags)."""
    m = ctx.m
    b, t = _days(ctx)
    c = b.c
    with np.errstate(invalid="ignore", divide="ignore"):
        RJ = c / pd.DataFrame(c).shift(7 * p["J"]).to_numpy() - 1
    weeks = ((t - pd.Timestamp("2017-01-02")).days // 7).to_numpy()
    reb = (t.dayofweek.to_numpy() == 6) & (weeks % p["K"] == 0)
    with np.errstate(invalid="ignore"):
        elig = np.isfinite(RJ) & (RJ <= -p["L"]) & reb[:, None]
    score = np.where(elig, RJ, np.inf)
    rank = score.argsort(axis=1).argsort(axis=1)
    sig = elig & (rank < 2)
    prio = on_grid(m, b, np.where(np.isfinite(RJ), -RJ, 0.0))
    return _trades(ctx, on_grid(m, b, sig, bool), np.nan_to_num(prio), _const(m, 0.20), _const(m, np.inf),
                   _const(m, 0.0), 7 * p["K"] * BARS_1D, 0, 0.20, 0.20, 2, cost, start, end, min_frac=0.10, extend=True)


TOM_GRID = [dict(pre=a, post=z, mode=md) for a, z, md in itertools.product((1, 2, 3), (2, 3, 4, 5), (1, 2))]
TOM_GEMINI = dict(pre=1, post=3, mode=2)


def run_tom(ctx, p, cost, start, end):
    """Kandidat 3 (Kumar 2022, Vasileiou 2023): BTC (und ETH) nur rund um den Monatswechsel halten."""
    m = ctx.m
    b, t = _days(ctx)
    on = t.day.to_numpy() == t.days_in_month.to_numpy() - p["pre"]
    sig = np.zeros(b.c.shape, bool)
    for j in range(p["mode"]):                          # 0 = BTC, 1 = ETH
        sig[:, j] = on & np.isfinite(b.c[:, j])
    return _trades(ctx, on_grid(m, b, sig, bool), np.zeros((m.N, m.K)), _const(m, 0.08), _const(m, np.inf),
                   _const(m, 0.0), (p["pre"] + p["post"]) * BARS_1D, 0, 0.30, 0.30, 2, cost, start, end, min_frac=0.15)


TRB_GRID = [dict(ne=a, nx=z, band=bb) for a, z, bb in itertools.product((50, 100, 150), (25, 50, 100), (0.0, 0.005, 0.01))]
TRB_GEMINI = dict(ne=50, nx=25, band=0.005)


def run_trb(ctx, p, cost, start, end):
    """Kandidat 4 (Hudson & Urquhart 2021): Tagesschluss über dem n-Tage-Hoch kaufen, unter dem n-Tage-Tief raus (ohne BTC)."""
    m = ctx.m
    b, _ = _days(ctx)
    c = b.c
    cdf = pd.DataFrame(c).shift(1)
    res = (1 + p["band"]) * cdf.rolling(p["ne"], min_periods=int(0.8 * p["ne"])).max().to_numpy()
    sup = (1 - p["band"]) * cdf.rolling(p["nx"], min_periods=int(0.8 * p["nx"])).min().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        sig = c > res
        ex = c < sup
        strength = np.nan_to_num(c / res - 1)
    sig[:, 0] = False                                   # BTC ausgenommen (laut Quelle dort kein Vorteil mehr)
    return _trades(ctx, on_grid(m, b, sig, bool), np.nan_to_num(on_grid(m, b, strength)), _const(m, 0.15),
                   _const(m, np.inf), _const(m, 0.0), 10 ** 9, 0, 0.25, 0.25, 2, cost, start, end, min_frac=0.125,
                   exit_sig=on_grid(m, b, ex, bool))


DDVOL_GRID = [dict(W=w, dd=d_, R=r) for w, d_, r in itertools.product((14, 21, 30), (0.04, 0.06, 0.08), (3, 7, 14))]
DDVOL_GEMINI = dict(W=21, dd=0.06, R=7)


def run_ddvol(ctx, p, cost, start, end, module=0.40):
    """Kandidat 5 (Gemini-Konstruktion): Top-2 nach rollierender Sharpe, Gewicht ~ Sharpe/Volatilität, Modul 40 %,
    alles verkaufen bei 6 % Modul-Drawdown, 1 Tag Pause."""
    m = ctx.m
    d = daily_ctx(ctx)
    b = d["b"]
    c = b.c[:, :5]                                      # BTC, ETH, SOL, BNB, XRP
    with np.errstate(invalid="ignore", divide="ignore"):
        R = pd.DataFrame(c / pd.DataFrame(c).shift(1).to_numpy() - 1)
        mu = R.rolling(p["W"], min_periods=p["W"]).mean().to_numpy()
        sd = R.rolling(p["W"], min_periods=p["W"]).std().to_numpy()
        S = mu / sd
        score = S / sd
    elig = np.isfinite(S) & (S > 0.10)
    key = np.where(elig, -S, np.inf)
    rank = key.argsort(axis=1).argsort(axis=1)
    pick = elig & (rank < 2)
    w = np.where(pick, score, 0.0)
    tot = w.sum(axis=1, keepdims=True)
    w = np.where(tot > 0, w / np.where(tot > 0, tot, 1.0), 0.0)
    W = np.zeros((len(c), m.K))
    W[:, :5] = w
    days = np.flatnonzero(d["ok"])
    days = days[days % p["R"] == 0]
    rebal = d["ends"][days]
    keep = rebal >= 0
    eq, _, orders, trips = engine.sim_weights_dd(m.CF, m.EP, W[days][keep], rebal[keep].astype(np.int64), float(cost),
                                                 0.10, float(p["dd"]), BARS_1D, int(start), int(end))
    r = np.nan_to_num(np.diff(eq) / eq[:-1])
    acc = np.full(m.N, np.nan)
    acc[start:end] = np.concatenate([[1.0], np.cumprod(1 + module * r[start:end - 1])])
    return acc, dict(orders=orders, trips=trips)


MONDAY_GRID = [dict(wd=w, h=h, f=f) for w, h, f in itertools.product((6, 1, 3), (1, 2), ("none", "pos", "neg"))]
MONDAY_GEMINI = dict(wd=6, h=1, f="none")


def run_monday(ctx, p, cost, start, end):
    """Kandidat 6 (Caporale & Plastun 2019): BTC nach dem Schluss eines Wochentags kaufen (Standard: Montag), h Tage halten."""
    m = ctx.m
    b, t = _days(ctx)
    c = b.c[:, 0]
    with np.errstate(invalid="ignore", divide="ignore"):
        prev = c / np.concatenate([[np.nan], c[:-1]]) - 1
    on = (t.dayofweek.to_numpy() == p["wd"]) & np.isfinite(c)
    if p["f"] == "pos":
        on &= prev > 0
    elif p["f"] == "neg":
        on &= prev < 0
    sig = np.zeros(b.c.shape, bool)
    sig[:, 0] = on
    return _trades(ctx, on_grid(m, b, sig, bool), np.zeros((m.N, m.K)), _const(m, 0.06), _const(m, np.inf),
                   _const(m, 0.0), p["h"] * BARS_1D, 0, 0.30, 0.30, 1, cost, start, end, min_frac=0.15)


ROUND2B = ("LOWVOL", "PASTLOSER", "TOM", "TRB", "DDVOL", "MONDAY")
GEMINI2_DEFAULTS = {"LOWVOL": LOWVOL_GEMINI, "PASTLOSER": PASTLOSER_GEMINI, "TOM": TOM_GEMINI, "TRB": TRB_GEMINI,
                    "DDVOL": DDVOL_GEMINI, "MONDAY": MONDAY_GEMINI}


# ====================================================================== Register
FAMILIES = {
    "TREND4H": (TREND_GRID, run_trend),
    "CRASH": (CRASH_GRID, run_crash),
    "TSMOM": (TSMOM_GRID, run_tsmom),
    "XSMOM": (XSMOM_GRID, run_xsmom),
    "CORE": (CORE_GRID, run_core),
    "PULLBACK": (PULLBACK_GRID, run_pullback),
    "TRANCHE": (TRANCHE_GRID, run_tranche),
    "LOWVOL": (LOWVOL_GRID, run_lowvol),
    "PASTLOSER": (PASTLOSER_GRID, run_pastloser),
    "TOM": (TOM_GRID, run_tom),
    "TRB": (TRB_GRID, run_trb),
    "DDVOL": (DDVOL_GRID, run_ddvol),
    "MONDAY": (MONDAY_GRID, run_monday),
}
BENCHMARKS = {
    "CASH": dict(what="cash"), "BTC_HALTEN": dict(what="btc"), "ALLE_HALTEN": dict(what="ew"),
    "ALLE_HALTEN_50": dict(what="ew", frac=0.5),
}


# ====================================================================== KOMBI (NewTry-Bot: ein gemeinsames Depot)
KOMBI_NEWTRY = dict(trend=TREND_NEWTRY, crash=CRASH_NEWTRY, risk=0.01, cap=0.33, k_trend=3, size=0.20, k_crash=3,
                    cooldown=96)


def run_kombi(ctx, p, cost, start, end):
    m = ctx.m
    t, c = p["trend"], p["crash"]
    sigA, stopA, tgtA = trend_signals(ctx, t["n"], t["sl"], t["tp"])
    sigB, _ = crash_signals(ctx, c["x"], c["lb"])
    if p.get("size", 0.2) <= 0:
        sigB = _no(m)
    eq, tr = engine.sim_joint(m.O, m.H, m.L, m.CF, m.EP, sigA, stopA, tgtA, int(t["mb"] * BARS_4H), float(p["risk"]),
                              float(p["cap"]), int(p["k_trend"]), 0.02, sigB, float(c["s"]), int(c["h"]),
                              float(max(p.get("size", 0.2), 1e-9)), int(p["k_crash"]), int(p["cooldown"]), float(cost),
                              int(start), int(end))
    return eq, tr
