"""
Ausfall-Test mit echten Kursen: Der Bot läuft, fällt dann für einige Stunden aus (nur Binance arbeitet weiter und prüft
jede Minute die Stop-Orders), startet neu und muss alles richtig buchen.
Aufruf: python -I research/outage.py <cache> <newtry-dir> <start> <ausfall-beginn> <ausfall-stunden> <ende>
Beispiel: ... 2021-05-01 2021-05-19 24 2021-05-21   (Ausfall genau über den Crash vom 19. Mai 2021)
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[0]).resolve().parent))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from replay import BOT_SETTINGS, load_data, replay_exchange  # noqa: E402

cache, app = Path(sys.argv[1]), sys.argv[2]
start, outage_start, hours = sys.argv[3], sys.argv[4], float(sys.argv[5])
ReplayExchange = replay_exchange(app)
from fakes import Clock, make_bot  # noqa: E402


def ms(day: str) -> int:
    return int(pd.Timestamp(day).timestamp() * 1000)


data = load_data(cache)
clock = Clock(ms(start))
exchange = ReplayExchange(clock, data)
state_dir = Path(tempfile.mkdtemp())
bot, _ = make_bot(state_dir, exchange, clock, exchange_stop=True, **BOT_SETTINGS)
bot.startup()
while clock() * 1000 < ms(outage_start):
    clock.advance(10 if bot.st["positions"] else 60)
    bot.tick()
held = {s: dict(p) for s, p in bot.st["positions"].items()}
print(f"Ausfall ab {outage_start} für {hours:g} h. Offene Positionen:")
for s, p in held.items():
    print(f"  {s}: Einstieg {p['entry_price']:.4f}, Stop im Bot {p['stop']:.4f}, Notbremse bei Binance {p.get('ex_stop') or 0:.4f}")
outage_end = ms(outage_start) + int(hours * 3_600_000)
while clock() * 1000 < outage_end:                    # Bot und Server aus – nur Binance arbeitet
    clock.advance(60)
    exchange.process_stops()
bot2, telegram2 = make_bot(state_dir, exchange, clock, exchange_stop=True, **BOT_SETTINGS)
bot2.startup()
for s, p in held.items():
    c = s.split("/")[0]
    d = data[c]
    i0, i1 = np.searchsorted(d["t"], ms(outage_start)), np.searchsorted(d["t"], outage_end)
    low, now = d["l"][i0:i1].min(), exchange.price(c)
    trade = next((t for t in reversed(bot2.st["closed"]) if t["symbol"] == s), None)
    print(f"  {c}: tiefster Kurs im Ausfall {low:.4f} ({(low / p['entry_price'] - 1) * 100:+.1f} %), beim Neustart "
          f"{now:.4f} ({(now / p['entry_price'] - 1) * 100:+.1f} %)")
    if trade and trade["reason"].startswith("Notbremse"):
        print(f"     Notbremse hat verkauft zu {trade['exit_price']:.4f}: {trade['pnl_pct']:+.1f} % ({trade['pnl']:+.2f} USDC)")
    elif s in bot2.st["positions"]:
        print("     Position noch offen (Notbremse nicht ausgelöst)")
print(f"Nach dem Neustart offen: {list(bot2.st['positions'])} · fälschlich als Einzahlung gezählt: "
      f"{any('Einzahlung' in m for m in telegram2.sent)} · Fehler: {[m for m in telegram2.sent if '❗' in m]}")
