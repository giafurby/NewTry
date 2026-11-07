"""
Teil 3: Beide Regeln in EINEM Depot (15m-Zeitachse), so wie der Bot es umsetzen würde.
  Trend:   4h-Schluss > Hoch der vorherigen 100 4h-Kerzen und >= EMA200(4h); Stop 2 ATR, Ziel 15 ATR, max 120 4h-Kerzen;
           Größe = Risiko r_b / Stop-Abstand, höchstens c_b des Kapitals; höchstens kb Positionen.
  Einbruch: 15m-Schluss >= X unter dem Schluss vor 16 Kerzen (4 h); Größe f_d des Kapitals; Notstop −s; nach 16 Kerzen raus;
           höchstens kd Positionen.
  Gemeinsam: je Coin nur eine Position, nur mit freiem Geld, optional Tageslimit (keine neuen Käufe nach −day % am Tag).
Aufruf: python -I combo.py <cache> <research-dir>
"""
import sys

sys.path.insert(0, sys.argv[2])
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.argv = [sys.argv[0], sys.argv[1], "15m"]
import dip  # noqa: E402

T, N, O, H, L, CL, live, SYM = dip.T, dip.N, dip.O, dip.H, dip.L, dip.CL, dip.live, dip.SYMBOLS
K = len(SYM)
split = dip.split_i
STEP = 900_000
FOUR = 4 * 3_600_000

# ---- 4h-Kennzahlen aus den 15m-Daten (exakt wie Binance: Blöcke ab 00:00 UTC)
blk = (T // FOUR)
trend_sig = np.zeros((N, K), bool)
trend_stopf = np.full((N, K), np.nan)
trend_tpf = np.full((N, K), np.nan)
for j in range(K):
    df = pd.DataFrame({"b": blk, "o": O[:, j], "h": H[:, j], "l": L[:, j], "c": dip.CL[:, j], "live": live[:, j]})
    g = df[df["live"]].groupby("b")
    four = pd.DataFrame({"h": g["h"].max(), "l": g["l"].min(), "c": g["c"].last(), "last_i": g.apply(lambda x: x.index[-1])})
    four = four[four.index < blk[-1]]           # nur geschlossene 4h-Kerzen
    c = four["c"]
    prior = four["h"].shift(1).rolling(100, min_periods=100).max()
    ema = c.ewm(span=200, adjust=False, min_periods=200).mean()
    pc = c.shift(1)
    tr = pd.concat([four["h"] - four["l"], (four["h"] - pc).abs(), (four["l"] - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    ok = (c > prior) & (c >= ema)
    # Signal gilt am letzten 15m-Bar der 4h-Kerze – aber nur, wenn das der echte Kerzenschluss ist
    ends = four["last_i"].to_numpy()
    full = (T[ends] + STEP) % FOUR == 0
    rows = ends[ok.to_numpy() & full]
    trend_sig[rows, j] = True
    trend_stopf[ends, j] = np.maximum(2 * (atr / c).to_numpy(), 0.002)
    trend_tpf[ends, j] = 15 * (atr / c).to_numpy()


def dip_signal(x):
    sig = dip.drop_signal(16, x)
    gap = np.zeros_like(sig)
    for k in range(0, 17):
        gap |= np.vstack([np.zeros((k, K), bool), ~live[: N - k]])
    return sig & ~gap


def run(use_trend=True, use_dip=True, r_b=0.01, c_b=0.33, kb=3, x=0.08, f_d=0.2, s=0.15, kd=5, cost=0.003,
        day_limit=None, start=0, end=None, hold_d=16, cooldown=0, dip_coins=None):
    end = N if end is None else end
    dsig = dip_signal(x) if use_dip else np.zeros((N, K), bool)
    if dip_coins is not None:
        dsig = dsig & np.array([sym[:-4] in dip_coins for sym in SYM])[None, :]
    blocked_until = np.zeros(K, int)
    cash = 1.0
    pos = {}   # j -> (kind, entry_bar, entry, units, stop, target, max_bars)
    trades = []
    curve_t, curve_v = [], []
    last_day, day_start = None, 1.0
    for i in range(start, end - 1):
        for j in list(pos):
            kind, eb, ep, u, sp, tg, mb = pos[j]
            lo, hi, op, cl = L[i, j], H[i, j], O[i, j], CL[i, j]
            px = None
            if np.isfinite(lo):
                if lo <= sp:
                    px = min(sp, op)
                elif hi >= tg:
                    px = max(tg, op)
            if px is None and i - eb + 1 >= mb and np.isfinite(cl):
                px = cl
            if px is not None:
                cash += u * px * (1 - cost)
                trades.append((kind, T[eb], j, px / ep * (1 - cost) ** 2 - 1))
                if kind == "dip" and px <= sp:
                    blocked_until[j] = i + cooldown
                del pos[j]
        value = cash + sum(u * (CL[i, j] if np.isfinite(CL[i, j]) else ep) for j, (_, _, ep, u, _, _, _) in pos.items())
        day = T[i] // 86_400_000
        if day != last_day:
            curve_t.append(T[i]); curve_v.append(value); last_day = day; day_start = value
        blocked = day_limit is not None and value < day_start * (1 - day_limit)
        if blocked:
            continue
        n_trend = sum(1 for p in pos.values() if p[0] == "trend")
        n_dip = len(pos) - n_trend
        if use_trend and n_trend < kb:
            for j in np.flatnonzero(trend_sig[i]):
                if j in pos or n_trend >= kb or not np.isfinite(O[i + 1, j]):
                    continue
                stopf = trend_stopf[i, j]
                if not np.isfinite(stopf) or stopf > 0.10:
                    continue
                budget = min(value * r_b / stopf, value * c_b, cash)
                if budget < value * 0.02:
                    continue
                ep = O[i + 1, j]
                cash -= budget
                pos[j] = ("trend", i + 1, ep, budget * (1 - cost) / ep, ep * (1 - stopf), ep * (1 + trend_tpf[i, j]), 1920)   # 120 4h-Kerzen = 1920 15m-Kerzen = 20 Tage
                n_trend += 1
        if use_dip and n_dip < kd:
            for j in np.flatnonzero(dsig[i]):
                if j in pos or n_dip >= kd or not np.isfinite(O[i + 1, j]) or i < blocked_until[j]:
                    continue
                budget = min(value * f_d, cash)
                if budget < value * f_d * 0.5:
                    continue
                ep = O[i + 1, j]
                cash -= budget
                pos[j] = ("dip", i + 1, ep, budget * (1 - cost) / ep, ep * (1 - s), np.inf, hold_d)
                n_dip += 1
    eq = pd.Series(curve_v, index=pd.to_datetime(curve_t, unit="ms"))
    return eq, trades


def show(name, eq, trades):
    def st(e):
        yrs = (e.index[-1] - e.index[0]).days / 365.25
        return (e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1, float((1 - e / e.cummax()).max())
    a, b = st(eq[eq.index < "2023-01-01"]), st(eq[eq.index >= "2023-01-01"])
    full_cagr, full_dd = st(eq)
    yearly = eq.groupby(eq.index.year).last() / eq.groupby(eq.index.year).first() - 1
    kinds = pd.Series([t[0] for t in trades]).value_counts().to_dict()
    print(f"{name:<52} gesamt {full_cagr:+6.1%}/DD {full_dd:4.0%} | IS {a[0]:+6.1%}/DD {a[1]:4.0%} | OOS {b[0]:+6.1%}/DD {b[1]:4.0%} | "
          f"neg. Jahre {int((yearly < 0).sum())} | " + " ".join(f"{str(y)[2:]}:{r:+.0%}" for y, r in yearly.items()) + f" | {kinds}")
    return eq


if __name__ == "__main__":
    for cost in (0.003, 0.0015):
        print(f"\n##### Kosten {cost:.2%} je Seite #####")
        e1 = show("nur Trend (1 % Risiko, max 3)", *run(use_dip=False, cost=cost))
        e2 = show("nur Einbruch (−8 %/4 h, 20 %, max 5, Stop −15 %)", *run(use_trend=False, cost=cost))
        corr = e1.pct_change().corr(e2.pct_change())
        print(f"   Korrelation der Tagesrenditen Trend/Einbruch: {corr:+.2f}")
        show("BEIDE (Trend 1 %/max 3 + Einbruch 20 %/max 5)", *run(cost=cost))
        show("BEIDE, Einbruch nur 15 %/max 3", *run(f_d=0.15, kd=3, cost=cost))
        show("BEIDE, Trend 1,5 % Risiko", *run(r_b=0.015, cost=cost))
        show("BEIDE, Trend 2 % Risiko + Einbruch 20 %", *run(r_b=0.02, cost=cost))
        show("BEIDE + Tageslimit −6 %", *run(cost=cost, day_limit=0.06))
        show("BEIDE, Einbruch ab −10 %", *run(x=0.10, cost=cost))
        show("BEIDE, Einbruch ab −6 %", *run(x=0.06, cost=cost))
