"""
Teil 2: Trendfolge/Momentum als Depot (gleiche Kosten 0,15 % bzw. 0,30 % je Seite), IS bis 2022, OOS ab 2023.
  a) Benchmarks: BTC halten, alle Coins gleich gewichtet halten
  b) Trendfilter je Coin: halten, solange Tagesschluss > SMA(N); je Coin 1/k des Kapitals
  c) Momentum-Rotation: wöchentlich die k stärksten Coins (Rendite über L Tage), nur wenn diese Rendite > 0
  d) 4h-Ausbruch (alte Regel und Varianten): Ereignis-Simulation mit ATR-Stop/Ziel und Risiko-Größe
Aufruf: python -I trend.py <cache>
"""
import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

C = Path(sys.argv[1])
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "TRXUSDT", "DOGEUSDT", "ZECUSDT", "ADAUSDT", "BCHUSDT"]
SPLIT = pd.Timestamp("2023-01-01")


def stats(equity: pd.Series) -> dict:
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1
    dd = float((1 - equity / equity.cummax()).max())
    daily = equity.pct_change().dropna()
    sharpe = daily.mean() / daily.std() * np.sqrt(365) if daily.std() > 0 else 0
    return dict(cagr=cagr, dd=dd, sharpe=sharpe)


def fmt(name, eq):
    a, b = stats(eq[eq.index < SPLIT]), stats(eq[eq.index >= SPLIT])
    yearly = eq.groupby(eq.index.year).last() / eq.groupby(eq.index.year).first() - 1
    return (f"{name:<46} IS {a['cagr']:+7.1%}/DD {a['dd']:4.0%}/Sh {a['sharpe']:4.2f} | OOS {b['cagr']:+7.1%}/DD {b['dd']:4.0%}"
            f"/Sh {b['sharpe']:4.2f} | " + " ".join(f"{str(y)[2:]}:{r:+.0%}" for y, r in yearly.items()))


# ---------------------------------------------------------------- Tagesdaten
closes = {}
for s in SYMBOLS:
    d = np.load(C / f"{s}_1d.npz")
    closes[s] = pd.Series(d["c"], index=pd.to_datetime(d["t"], unit="ms"))
P = pd.DataFrame(closes).sort_index()
R = P.pct_change(fill_method=None)


def run_weights(W: pd.DataFrame, cost: float) -> pd.Series:
    """W[t] = Zielgewichte nach dem Schluss von Tag t (gehandelt zum Schluss t), Rendite von t nach t+1."""
    W = W.fillna(0.0)
    turnover = W.diff().abs().sum(axis=1).fillna(W.abs().sum(axis=1))
    port = (W.shift(1) * R).sum(axis=1) - cost * turnover.shift(1).fillna(0.0)
    return (1 + port).cumprod()


def sma_filter(n, k, cost):
    sma = P.rolling(n).mean()
    W = (P > sma).astype(float) / k
    W = W.where(P.notna(), 0.0)
    return run_weights(W, cost)


def momentum(lookback, k, cost, abs_filter=True):
    mom = P / P.shift(lookback) - 1
    W = pd.DataFrame(0.0, index=P.index, columns=P.columns)
    current = pd.Series(0.0, index=P.columns)
    for day in P.index:
        if day.day_of_week == 0:                       # montags umschichten
            row = mom.loc[day].dropna()
            if abs_filter:
                row = row[row > 0]
            top = row.sort_values(ascending=False).head(k).index
            current = pd.Series(0.0, index=P.columns)
            current[top] = 1.0 / k
        W.loc[day] = current
    return run_weights(W, cost)


# ---------------------------------------------------------------- 4h-Ereignis-Simulation
def bars4h():
    out = {}
    for s in SYMBOLS:
        d = np.load(C / f"{s}_1h.npz")
        f = pd.DataFrame({k: d[k] for k in "ohlc"}, index=pd.to_datetime(d["t"], unit="ms"))
        out[s] = f.resample("4h").agg({"o": "first", "h": "max", "l": "min", "c": "last"}).dropna()
    return out


def breakout(frames, n, sl, tp, max_bars, risk, kmax, cost, ema_n=200):
    idx = sorted(set().union(*[f.index for f in frames.values()]))
    idx = pd.DatetimeIndex(idx)
    cols = {}
    for s, f in frames.items():
        f = f.reindex(idx)
        c = f["c"]
        prior = f["h"].shift(1).rolling(n, min_periods=n).max()
        ema = c.ewm(span=ema_n, adjust=False, min_periods=ema_n).mean()
        pc = c.shift(1)
        tr = pd.concat([f["h"] - f["l"], (f["h"] - pc).abs(), (f["l"] - pc).abs()], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        sig = (c > prior) & (c >= ema)
        cols[s] = (f["o"].to_numpy(), f["h"].to_numpy(), f["l"].to_numpy(), c.ffill().to_numpy(),
                   sig.to_numpy(), (atr / c).to_numpy())
    equity, cash = 1.0, 1.0
    pos = {}
    curve = []
    day_of = idx.floor("D")
    last_day = None
    for i in range(len(idx) - 1):
        for s in list(pos):
            o, h, l, c, _, _ = cols[s]
            eb, ep, units, stop, target = pos[s]
            px = None
            if np.isfinite(l[i]):
                if l[i] <= stop:
                    px = min(stop, o[i])
                elif h[i] >= target:
                    px = max(target, o[i])
                elif i - eb + 1 >= max_bars:
                    px = c[i]
            if px is not None:
                cash += units * px * (1 - cost)
                del pos[s]
        value = cash + sum(u * cols[s][3][i] for s, (eb, ep, u, st, tg) in pos.items())
        day = day_of[i]
        if day != last_day:
            curve.append((idx[i], value)); last_day = day
        for s, (o, h, l, c, sig, atrf) in cols.items():
            if len(pos) >= kmax or s in pos or not sig[i] or not np.isfinite(o[i + 1]):
                continue
            stop_f = max(sl * atrf[i], 0.002)
            if stop_f > 0.10:
                continue
            budget = min(value * risk / stop_f, value / kmax, cash)
            if budget < value * 0.01:
                continue
            ep = o[i + 1]
            cash -= budget
            pos[s] = [i + 1, ep, budget * (1 - cost) / ep, ep * (1 - stop_f), ep * (1 + tp * atrf[i])]
    eq = pd.Series([v for _, v in curve], index=[t for t, _ in curve])
    return eq


if __name__ == "__main__":
    for cost in (0.0015, 0.003):
        print(f"\n######## Kosten {cost:.2%} je Seite ########")
        print(fmt("BTC halten", run_weights(pd.DataFrame({"BTCUSDT": P["BTCUSDT"].notna().astype(float)}).reindex(columns=P.columns), cost)))
        ew = P.notna().astype(float).div(P.notna().sum(axis=1), axis=0)
        print(fmt("Alle Coins gleich gewichtet halten", run_weights(ew, cost)))
        for n, k in itertools.product((20, 50, 100, 200), (5, 10)):
            print(fmt(f"Trendfilter SMA{n}, je Coin 1/{k}", sma_filter(n, k, cost)))
        for lookback, k in itertools.product((14, 30, 60, 90), (1, 2, 3)):
            print(fmt(f"Momentum {lookback} Tage, Top {k}, nur positiv", momentum(lookback, k, cost)))
    frames = bars4h()
    print("\n######## 4h-Ausbruch (Kosten 0,15 % / 0,30 %), Risiko 1 %/Trade, max. 3 Positionen ########")
    for cost in (0.0015, 0.003):
        for n, sl, tp, mb in ((100, 2, 15, 120), (100, 2, 12, 40), (50, 2, 15, 120), (200, 2, 15, 120), (100, 3, 15, 120),
                              (100, 2, 8, 120), (55, 3, 1000, 240)):
            eq = breakout(frames, n, sl, tp, mb, 0.01, 3, cost)
            print(fmt(f"Ausbruch {n}, Stop {sl} ATR, Ziel {tp} ATR, {mb} Kerzen ({cost:.2%})", eq))
    for risk, kmax in ((0.02, 3), (0.02, 5), (0.03, 5)):
        eq = breakout(frames, 100, 2, 15, 120, risk, kmax, 0.003)
        print(fmt(f"Ausbruch 100 (alte Regel), Risiko {risk:.0%}, max {kmax} (0,30 %)", eq))
