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
            cooldown=0, min_frac=0.02, part_frac=0.0, part_tgt=0.0, exit_sig=None):
    m = ctx.m
    eq, tr = engine.sim_trades(m.O, m.H, m.L, m.CF, m.EP, sig, prio, stopf, tgtf, trailf, int(hold), float(part_frac),
                               float(part_tgt), int(size_mode), float(size_a), float(size_cap), int(kmax), float(cost),
                               int(cooldown), int(start), int(end), float(min_frac),
                               _no(m) if exit_sig is None else exit_sig)
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


# ====================================================================== Register
FAMILIES = {
    "TREND4H": (TREND_GRID, run_trend),
    "CRASH": (CRASH_GRID, run_crash),
    "TSMOM": (TSMOM_GRID, run_tsmom),
    "XSMOM": (XSMOM_GRID, run_xsmom),
    "CORE": (CORE_GRID, run_core),
    "PULLBACK": (PULLBACK_GRID, run_pullback),
    "TRANCHE": (TRANCHE_GRID, run_tranche),
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
