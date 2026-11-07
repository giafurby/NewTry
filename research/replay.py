"""
Echte Kurse durch den echten Bot-Code spielen und mit der Forschungs-Simulation vergleichen.
Aufruf: python -I replay.py <cache> <research-dir> <newtry-dir> <start YYYY-MM-DD> <ende YYYY-MM-DD>
"""
import sys
import tempfile
from pathlib import Path

CACHE, RES, APP = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
START, END = sys.argv[4], sys.argv[5]
sys.path.insert(0, APP)
sys.path.insert(0, str(Path(APP) / "tests"))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import strategy  # noqa: E402
from fakes import Clock, FakeExchange, make_bot  # noqa: E402

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "TRX", "DOGE", "ZEC", "ADA", "BCH"]
M15, H4 = 900_000, 14_400_000
data = {}
for c in COINS:
    d = np.load(CACHE / f"{c}USDT_15m.npz")
    h = np.load(CACHE / f"{c}USDT_1h.npz")
    f = pd.DataFrame({k: h[k] for k in "ohlcv"}, index=pd.to_datetime(h["t"], unit="ms"))
    four = f.resample("4h").agg({"o": "first", "h": "max", "l": "min", "c": "last", "v": "sum"}).dropna()
    data[c] = dict(t=d["t"], o=d["o"], h=d["h"], l=d["l"], c=d["c"], v=d["v"],
                   t4=four.index.as_unit("ms").asi8,
                   o4=four["o"].to_numpy(), h4=four["h"].to_numpy(), l4=four["l"].to_numpy(), c4=four["c"].to_numpy())


class ReplayExchange(FakeExchange):
    def __init__(self, clock):
        super().__init__({"USDC": 150.0}, {f"{c}/USDC": 1.0 for c in COINS}, step=1e-8, min_cost=5.0)
        self.clock = clock
        self.slippage = 0.0005

    def _bar(self, coin):
        d = data[coin]
        now = int(self.clock() * 1000)
        i = int(np.searchsorted(d["t"], now, side="right")) - 1
        return d, i, now

    def price(self, coin):
        d, i, now = self._bar(coin)
        if i < 0:
            return float(d["o"][0])
        if d["t"][i] + M15 <= now:                       # Lücke (Wartung): letzter Schluss
            return float(d["c"][i])
        frac = (now - d["t"][i]) / M15
        o, h, l, c = d["o"][i], d["h"][i], d["l"][i], d["c"][i]
        path = (o, l, h, c) if c >= o else (o, h, l, c)  # innerhalb der Kerze: erst Gegenrichtung, dann Schluss
        seg = min(int(frac * 3), 2)
        w = frac * 3 - seg
        return float(path[seg] + (path[seg + 1] - path[seg]) * w)

    def current_price(self, symbol):
        return self.price(symbol.split("/")[0])

    def fetch_tickers(self, symbols=None):
        return {s: {"symbol": s, "last": self.price(s.split("/")[0])} for s in (symbols or self.prices)}

    def fetch_ohlcv(self, symbol, timeframe="4h", since=None, limit=None):
        coin = symbol.split("/")[0]
        d, i, now = self._bar(coin)
        p = self.price(coin)
        if timeframe == "15m":
            lo = max(0, i - (limit or 40) + 1)
            rows = [[int(d["t"][k]), d["o"][k], d["h"][k], d["l"][k], d["c"][k], d["v"][k]] for k in range(lo, i)]
            rows.append([int(d["t"][i]), d["o"][i], max(d["o"][i], p), min(d["o"][i], p), p, 1.0])
            return rows
        j = int(np.searchsorted(d["t4"], now, side="right")) - 1
        lo = max(0, j - (limit or 1000) + 1)
        rows = [[int(d["t4"][k]), d["o4"][k], d["h4"][k], d["l4"][k], d["c4"][k], 1.0] for k in range(lo, j)]
        rows.append([int(d["t4"][j]), d["o4"][j], max(d["o4"][j], p), min(d["o4"][j], p), p, 1.0])
        return rows


start_ms = int(pd.Timestamp(START).timestamp() * 1000)
end_ms = int(pd.Timestamp(END).timestamp() * 1000)
clock = Clock(start_ms)
exchange = ReplayExchange(clock)
tmp = Path(tempfile.mkdtemp())
bot, tg = make_bot(tmp, exchange, clock, coins=tuple(COINS), dip_enabled=True, dip_coins=tuple(COINS),
                   risk_per_trade_pct=1.0, max_positions=3, max_position_pct=33.0, daily_loss_limit_pct=0.0,
                   max_drawdown_pct=40.0, scan_reports=False, dip_max_positions=3)
bot.startup()
while clock() * 1000 < end_ms:
    clock.advance(10 if bot.st["positions"] else 60)
    bot.tick()
bot.refresh()
closed = [t for t in bot.st["closed"] if not t["selftest"]]
for kind in ("trend", "dip"):
    part = [t for t in closed if t["kind"] == kind]
    print(f"BOT {kind:<5}: {len(part):>3} Trades, Ø {np.mean([t['pnl_pct'] for t in part]) if part else 0:+.2f} %, "
          f"Summe {sum(t['pnl'] for t in part):+.2f} USDC  " +
          " ".join(f"{t['symbol'][:-5]}@{t['closed_at'][5:16]}:{t['pnl_pct']:+.1f}%" for t in part[:12]))
print(f"BOT Kapital {bot.equity:.2f} USDC (Start 150) → {bot.equity / 150 - 1:+.1%}, offen: {list(bot.st['positions'])}, "
      f"Fehlermeldungen: {[m for m in tg.sent if '❗' in m][:2]}")

# Forschungs-Simulation auf demselben Zeitraum (Kosten 0,15 %/Seite wie im Replay)
sys.argv = [sys.argv[0], str(CACHE), RES]
sys.path.insert(0, RES)
import combo  # noqa: E402
i0 = int(np.searchsorted(combo.T, start_ms)); i1 = int(np.searchsorted(combo.T, end_ms))
eq, tr = combo.run(x=0.10, f_d=0.2, kd=3, s=0.15, r_b=0.01, kb=3, c_b=0.33, hold_d=16, cooldown=96, cost=0.0015,
                   start=i0, end=i1)
t = pd.DataFrame(tr, columns=["kind", "t", "j", "ret"])
for kind in ("trend", "dip"):
    part = t[t["kind"] == kind]
    print(f"SIM {kind:<5}: {len(part):>3} Trades, Ø {part['ret'].mean() * 100 if len(part) else 0:+.2f} %  " +
          " ".join(f"{combo.SYM[r.j][:-4]}@{pd.Timestamp(r.t, unit='ms'):%m-%d %H:%M}:{r.ret * 100:+.1f}%"
                   for r in part.head(12).itertuples()))
print(f"SIM Kapital → {eq.iloc[-1] / eq.iloc[0] - 1:+.1%}")
