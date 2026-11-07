"""
Echte Kurse durch den echten Bot-Code spielen und mit der Forschungs-Simulation vergleichen.
Aufruf: python -I research/replay.py <cache> <research-dir> <newtry-dir> <start YYYY-MM-DD> <ende YYYY-MM-DD> [notbremse]
"""
import sys
import tempfile
from pathlib import Path

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "TRX", "DOGE", "ZEC", "ADA", "BCH"]
M15 = 900_000


def load_data(cache: Path) -> dict:
    import numpy as np
    import pandas as pd
    data = {}
    for c in COINS:
        d = np.load(cache / f"{c}USDT_15m.npz")
        h = np.load(cache / f"{c}USDT_1h.npz")
        f = pd.DataFrame({k: h[k] for k in "ohlcv"}, index=pd.to_datetime(h["t"], unit="ms"))
        four = f.resample("4h").agg({"o": "first", "h": "max", "l": "min", "c": "last", "v": "sum"}).dropna()
        data[c] = dict(t=d["t"], o=d["o"], h=d["h"], l=d["l"], c=d["c"], v=d["v"], t4=four.index.as_unit("ms").asi8,
                       o4=four["o"].to_numpy(), h4=four["h"].to_numpy(), l4=four["l"].to_numpy(), c4=four["c"].to_numpy())
    return data


def replay_exchange(app: str):
    """Klasse erst bauen, wenn der Pfad zu den Test-Fakes bekannt ist."""
    sys.path.insert(0, app)
    sys.path.insert(0, str(Path(app) / "tests"))
    import numpy as np
    from fakes import FakeExchange

    class ReplayExchange(FakeExchange):
        """Börse, die zur simulierten Uhrzeit die echten Kurse liefert (innerhalb einer 15m-Kerze erst Gegenrichtung)."""

        def __init__(self, clock, data):
            super().__init__({"USDC": 150.0}, {f"{c}/USDC": 1.0 for c in COINS}, step=1e-8, min_cost=5.0)
            for market in self.markets.values():
                market["precision"]["price"] = 1e-8
            self.clock, self.data = clock, data
            self.slippage = 0.0005

        def _bar(self, coin):
            d = self.data[coin]
            now = int(self.clock() * 1000)
            return d, int(np.searchsorted(d["t"], now, side="right")) - 1, now

        def price(self, coin):
            d, i, now = self._bar(coin)
            if i < 0:
                return float(d["o"][0])
            if d["t"][i] + M15 <= now:
                return float(d["c"][i])
            frac = (now - d["t"][i]) / M15
            o, h, l, c = d["o"][i], d["h"][i], d["l"][i], d["c"][i]
            path = (o, l, h, c) if c >= o else (o, h, l, c)
            seg = min(int(frac * 3), 2)
            return float(path[seg] + (path[seg + 1] - path[seg]) * (frac * 3 - seg))

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

    return ReplayExchange


BOT_SETTINGS = dict(coins=tuple(COINS), dip_enabled=True, dip_coins=tuple(COINS), risk_per_trade_pct=1.0, max_positions=3,
                    max_position_pct=33.0, daily_loss_limit_pct=0.0, max_drawdown_pct=40.0, scan_reports=False,
                    dip_max_positions=3)


def main() -> None:
    import numpy as np
    import pandas as pd
    cache, research, app, start, end = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
    exchange_stop = len(sys.argv) > 6 and sys.argv[6] == "notbremse"
    ReplayExchange = replay_exchange(app)
    from fakes import Clock, make_bot

    start_ms, end_ms = (int(pd.Timestamp(x).timestamp() * 1000) for x in (start, end))
    clock = Clock(start_ms)
    exchange = ReplayExchange(clock, load_data(cache))
    bot, tg = make_bot(Path(tempfile.mkdtemp()), exchange, clock, exchange_stop=exchange_stop, **BOT_SETTINGS)
    bot.startup()
    while clock() * 1000 < end_ms:
        clock.advance(10 if bot.st["positions"] else 60)
        bot.tick()
    bot.refresh()
    closed = [t for t in bot.st["closed"] if not t["selftest"]]
    for kind in ("trend", "dip"):
        part = [t for t in closed if t["kind"] == kind]
        print(f"BOT {kind:<5}: {len(part):>3} Trades, Ø {np.mean([t['pnl_pct'] for t in part]) if part else 0:+.2f} %, "
              f"Summe {sum(t['pnl'] for t in part):+.2f} USDC  "
              + " ".join(f"{t['symbol'][:-5]}@{t['closed_at'][5:16]}:{t['pnl_pct']:+.1f}%" for t in part[:12]))
    stops = [o for o in exchange.orders.values() if o.get("triggerPrice") is not None]
    print(f"Notbremsen: {len(stops)} gesetzt, ausgelöst {sum(1 for o in stops if o['filled'] > 0)}, storniert "
          f"{sum(1 for o in stops if o['status'] == 'canceled')}, offen {sum(1 for o in stops if o['status'] == 'open')}")
    print(f"BOT Kapital {bot.equity:.2f} USDC (Start 150), offen: {list(bot.st['positions'])}, "
          f"Fehlermeldungen: {[m for m in tg.sent if '❗' in m][:2]}")

    sys.argv = [sys.argv[0], str(cache), research]
    sys.path.insert(0, research)
    import combo
    i0, i1 = int(np.searchsorted(combo.T, start_ms)), int(np.searchsorted(combo.T, end_ms))
    eq, tr = combo.run(x=0.10, f_d=0.2, kd=3, s=0.15, r_b=0.01, kb=3, c_b=0.33, hold_d=16, cooldown=96, cost=0.0015,
                       start=i0, end=i1)
    t = pd.DataFrame(tr, columns=["kind", "t", "j", "ret"])
    for kind in ("trend", "dip"):
        part = t[t["kind"] == kind]
        print(f"SIM {kind:<5}: {len(part):>3} Trades, Ø {part['ret'].mean() * 100 if len(part) else 0:+.2f} %  "
              + " ".join(f"{combo.SYM[r.j][:-4]}@{pd.Timestamp(r.t, unit='ms'):%m-%d %H:%M}:{r.ret * 100:+.1f}%"
                         for r in part.head(12).itertuples()))


if __name__ == "__main__":
    main()
