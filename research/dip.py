"""
Teil 1b: "Einbruch kaufen" kritisch prüfen – als Depot mit echten Grenzen.
Signal (auf Kerzenschluss): Kurs mindestens X % unter dem Schluss vor M Kerzen. Einstieg Open der Folgekerze.
Ausstieg: nach H Kerzen (Close) – oder Notstop (Low <= Einstieg × (1 − s)) – oder Ziel (High >= Einstieg × (1 + tp)).
Depot: je Position Anteil f des Kapitals, höchstens K Positionen, je Coin nur eine.
Aufruf: python -I dip.py <cache> [tf]
"""
import sys
from pathlib import Path

import numpy as np

C = Path(sys.argv[1])
TF = sys.argv[2] if len(sys.argv) > 2 else "15m"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "TRXUSDT", "DOGEUSDT", "ZECUSDT", "ADAUSDT", "BCHUSDT"]
SPLIT = 1672531200000
STEP = {"15m": 900_000, "1h": 3_600_000}[TF]

# gemeinsame Zeitachse
raw = {s: np.load(C / f"{s}_{TF}.npz") for s in SYMBOLS}
t0 = min(int(d["t"][0]) for d in raw.values())
t1 = max(int(d["t"][-1]) for d in raw.values())
T = np.arange(t0, t1 + STEP, STEP)
N, K_ = len(T), len(SYMBOLS)
O, H, L, CL = (np.full((N, K_), np.nan) for _ in range(4))
for j, s in enumerate(SYMBOLS):
    d = raw[s]
    pos = ((d["t"] - t0) // STEP).astype(int)
    O[pos, j], H[pos, j], L[pos, j], CL[pos, j] = d["o"], d["h"], d["l"], d["c"]
# fehlende Kerzen (Wartung) mit letztem Schluss auffüllen, damit Positionen bewertbar bleiben
for A in (CL,):
    for j in range(K_):
        col = A[:, j]
        valid = np.isfinite(col)
        idx = np.where(valid, np.arange(N), 0)
        np.maximum.accumulate(idx, out=idx)
        first = np.argmax(valid)
        filled = col[idx]
        filled[:first] = np.nan
        A[:, j] = filled
live = np.isfinite(O)


def drop_signal(m, x):
    prev = np.vstack([np.full((m, K_), np.nan), CL[:-m]])
    with np.errstate(invalid="ignore"):
        return live & (CL / prev - 1 <= -x)


def simulate(sig, hold, stop, tp, f, kmax, cost, start=0, end=None, record=False):
    end = N if end is None else end
    equity = 1.0
    cash = 1.0
    positions = {}            # j -> [entry_bar, entry_price, units, stop_price, tp_price]
    trades = []
    curve_t, curve_v = [], []
    last_day = None
    for i in range(start, end - 1):
        # Ausstiege in Kerze i (nach Einstieg in einer früheren Kerze)
        for j in list(positions):
            eb, ep, units, sp, tpp = positions[j]
            lo, hi, op, cl = L[i, j], H[i, j], O[i, j], CL[i, j]
            px = None
            if np.isfinite(lo):
                if lo <= sp:
                    px = min(sp, op)
                elif hi >= tpp:
                    px = max(tpp, op)
            if px is None and i - eb + 1 >= hold and np.isfinite(cl):
                px = cl
            if px is not None:
                cash += units * px * (1 - cost)
                trades.append((T[eb], j, ep, px, px / ep * (1 - cost) ** 2 - 1))
                del positions[j]
        # Bewertung
        value = cash + sum(u * (CL[i, j] if np.isfinite(CL[i, j]) else ep) for j, (eb, ep, u, sp, tpp) in positions.items())
        day = T[i] // 86_400_000
        if day != last_day:
            curve_t.append(T[i]); curve_v.append(value); last_day = day
        # Einstiege: Signal auf Schluss i, Kauf zum Open i+1
        if len(positions) < kmax:
            for j in np.flatnonzero(sig[i]):
                if j in positions or len(positions) >= kmax or not np.isfinite(O[i + 1, j]):
                    continue
                budget = min(value * f, cash)
                if budget <= value * f * 0.5:
                    continue
                ep = O[i + 1, j]
                units = budget * (1 - cost) / ep
                cash -= budget
                positions[j] = [i + 1, ep, units, ep * (1 - stop) if stop else -1.0, ep * (1 + tp) if tp else np.inf]
    v = np.array(curve_v)
    years = (curve_t[-1] - curve_t[0]) / (365.25 * 86_400_000)
    cagr = v[-1] ** (1 / years) - 1 if years > 0 else 0
    peak = np.maximum.accumulate(v)
    mdd = float((1 - v / peak).max())
    rets = np.array([tr[4] for tr in trades])
    out = dict(cagr=cagr, mdd=mdd, final=v[-1], n=len(trades), win=float((rets > 0).mean()) if len(rets) else 0,
               avg=float(rets.mean()) if len(rets) else 0, worst=float(rets.min()) if len(rets) else 0)
    if record:
        out["curve"] = (np.array(curve_t), v)
        out["trades"] = trades
    return out


split_i = int(np.searchsorted(T, SPLIT))
if __name__ == "__main__":
    print(f"Zeitebene {TF}, {N} Kerzen, Aufteilung bei Index {split_i}")
    print("1) Grundvariante je Schwelle (ohne Stop), f=20 %, max 5 Positionen, Kosten 0,15 %/Seite")
    hold_bars = {"15m": (16, 32, 64), "1h": (8, 16, 32)}[TF]
    for m, x in ((4, 0.05), (4, 0.03), (16, 0.05), (16, 0.08)):
        sig = drop_signal(m, x)
        for hold in hold_bars:
            a = simulate(sig, hold, 0, 0, 0.2, 5, 0.0015, 0, split_i)
            b = simulate(sig, hold, 0, 0, 0.2, 5, 0.0015, split_i, N)
            print(f"  M={m:>2} X={x:.0%} H={hold:>3}: IS CAGR {a['cagr']:+7.1%} MaxDD {a['mdd']:5.1%} n={a['n']:>5} "
                  f"Ø {a['avg']:+.2%} Treffer {a['win']:.0%} schlechtester {a['worst']:+.0%} | OOS CAGR {b['cagr']:+7.1%} "
                  f"MaxDD {b['mdd']:5.1%} n={b['n']:>4} Ø {b['avg']:+.2%} schlechtester {b['worst']:+.0%}")
