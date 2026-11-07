# NewTry – schlanker Handelsbot für Binance Spot

Ein Neuanfang nach *azubiassist*: rund 1.900 Zeilen statt 27.000, eine geprüfte Regel, harte Verlustgrenzen, und er
**handelt wirklich**. Er übernimmt Binance- und Telegram-Schlüssel automatisch vom alten Bot auf dem Server.

## Was er macht

| | |
|---|---|
| **Markt** | Binance Spot, gekauft wird mit USDC (bzw. der Währung aus dem alten Bot). 25 Coins; Coins ohne USDC-Markt werden beim Start übersprungen. |
| **Kauf** | Eine **4h-Kerze schließt über dem Hoch der vorherigen 100 Kerzen** und liegt **über der EMA 200**. |
| **Verkauf** | **Stop** 2 × ATR unter dem Einstieg · **Ziel** 15 × ATR darüber · **spätestens nach 20 Tagen**. Kein Trailing-Stop. |
| **Takt** | Kaufsignale direkt nach jedem 4h-Kerzenschluss (Winterzeit: 01, 05, 09, 13, 17, 21 Uhr). Stop und Ziel alle 10 Sekunden. |
| **KI** | Bewusst **keine** im Handelsweg: keine API-Kosten, keine erfundenen Antworten, jede Entscheidung nachrechenbar. |

Die Regel stammt aus der Echtdaten-Studie des alten Projekts (echte Binance-Kerzen 2017 bis 10/2026, 10 Coins,
`azubiassist/ANLEITUNG_HETZNER.md` Teil 18 und 20). Der Code in `strategy.py` rechnet genau so wie der damalige Backtest
(EMA wie pandas, ATR nach Wilder, Stop mindestens 0,2 %; liegt er mehr als 10 % entfernt, wird der Trade ausgelassen).

## Schutz für dein Geld

| Grenze | Standard | Wirkung |
|---|---|---|
| Risiko je Trade | 1 % des Kapitals | Positionsgröße = Risiko ÷ Stop-Abstand (bei 150 USDC meist 20 bis 50 USDC) |
| Positionen | höchstens 3, je höchstens 33 % | nie alles auf einen Coin |
| Tageslimit | −6 % | bis Mitternacht keine neuen Käufe |
| Notstopp | −25 % vom Höchststand | **alles verkaufen und anhalten**, weiter nur mit `/weiter` |
| Doppelte Orders | ausgeschlossen | jede Order hat eine eigene Nummer; nach Netzfehler oder Absturz wird bei Binance nachgesehen, bevor neu gehandelt wird |
| Ein-/Auszahlungen | erkannt | zählen weder als Gewinn noch als Verlust und lösen keinen Notstopp aus |
| Fremde Bestände | unangetastet | der Bot verkauft nur, was er selbst gekauft hat |
| Funktionstest | einmal beim ersten Echtgeld-Start | Kauf und sofortiger Verkauf für ca. 7 USDC beweisen, dass Schlüssel und Orders funktionieren (Kosten: wenige Cent) |

## Ehrliche Erwartung

* Im Rückblick hat die Regel verdient: in der Depot-Simulation seit 2018 rund +34 % pro Jahr bei 0,75 % Risiko je Trade
  (größter Rückgang 17 %). **Das ist Vergangenheit.** Getestet wurden damals 45 Ausstiegs-Varianten, die Zukunft wird
  schwächer sein. Es gab Verlustjahre (2018, 2022).
* **Nur etwa jeder vierte Trade gewinnt.** 10 oder mehr Verluste hintereinander sind normal; der Gewinn kommt aus wenigen
  großen Treffern. Ein Trade dauert im Schnitt rund 6 Tage.
* Signale sind selten: im Schnitt einige pro Woche über alle Coins, in Abwärtsmärkten tagelang keins. **Dass der Bot dann
  nichts kauft, ist Absicht.** Die stille Meldung nach jeder 4h-Prüfung und `/markt` zeigen, wie nah die Coins dran sind.
* Mit rund 150 € Einsatz bedeuten selbst sehr gute Jahre einige Dutzend Euro. Setze nur Geld ein, dessen Verlust du
  verkraftest.

## Installation auf dem Server (etwa 5 Minuten)

1. **PC** (PowerShell): `ssh root@46.62.234.12`
2. **Server** – diese eine Zeile einfügen und Enter drücken:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/giafurby/NewTry/ccr-65a9ebf1-h1kqzu/install.sh -o /root/newtry-install.sh && bash /root/newtry-install.sh
   ```
3. Auf die Frage **`ECHTGELD`** eintippen (oder nur Enter für den Papiermodus).

Das Skript holt den Code nach `/root/newtry`, übernimmt die Schlüssel aus `/root/trading-bot/.env`, richtet Python ein
und macht eine **Startklar-Prüfung** (Binance erreichbar, Kontostand, Handelsrecht des Schlüssels, Telegram-Testnachricht).
**Erst wenn die Prüfung bestanden ist**, schaltet es den alten Bot ab (Code und Daten bleiben erhalten) und startet den
neuen Dienst `newtry-bot`. Scheitert sie, bleibt alles, wie es war, und das Skript sagt, woran es liegt.

**Updates** später mit derselben Zeile (oder `bash /root/newtry-install.sh`). Einstellungen und Positionen bleiben erhalten.

## Telegram

| Befehl | |
|---|---|
| `/status` | Kapital, Gewinn seit Start, offene Positionen mit Stop und Ziel, Grenzen |
| `/markt` | wie weit jeder Coin vom Kaufsignal entfernt ist |
| `/trades` | die letzten abgeschlossenen Trades |
| `/pause` · `/weiter` | keine neuen Käufe bzw. wieder kaufen (`/weiter` hebt auch den Notstopp auf) |
| `/notverkauf` | alle Positionen sofort verkaufen (mit Bestätigung `/notverkauf_ja`) |

Dazu kommen von selbst: jeder Kauf und Verkauf, eine stille Meldung nach jeder 4h-Prüfung, der Tagesbericht um 9 Uhr und
Warnungen (Binance länger nicht erreichbar, Schlüssel abgelehnt, Tageslimit, Notstopp).

## Auf dem Server

| Was | Befehl |
|---|---|
| Läuft er? | `systemctl is-active newtry-bot` |
| Live-Protokoll (Ende mit Strg+C) | `journalctl -u newtry-bot -f` |
| Anhalten / Starten | `systemctl stop newtry-bot` / `systemctl start newtry-bot` |
| Startklar-Prüfung | `cd /root/newtry && .venv/bin/python bot.py --check` |
| Papier ↔ Echtgeld | `bash /root/newtry-install.sh --paper` / `bash /root/newtry-install.sh --live` |
| Neue Binance-Schlüssel | `bash /root/newtry-install.sh --keys` |
| Einstellungen ändern | `nano /root/newtry/.env`, danach `systemctl restart newtry-bot` |
| Zurück zum alten Bot | `systemctl disable --now newtry-bot && systemctl enable --now trading-bot` |

Papier- und Echtgeld-Modus haben getrennte Gedächtnisse (`data/state-paper.json`, `data/state-live.json`), damit
simulierte Positionen nie im echten Konto landen. Alle Einstellungen mit Erklärung stehen in `.env.example`.

## Warum der alte Bot nie gehandelt hat

Mit Echtgeld startete er mit einer Kapital-Rampe von **5 %** des Kontos: 5 % von 150 USDC = 7,50 USDC. Bei halbem Risiko
im Probebetrieb ergab das Positionen von etwa **1,10 USDC**, Binance nimmt aber erst Orders ab 5 USDC an. Dazu kamen
Richter, Probebetrieb, Ampel und Freigabe-Stufen, die jeweils für sich vernünftig klangen, zusammen aber jeden Kauf
verhindert haben. NewTry hat eine einzige Regel und feste Grenzen, aber keine Hürde, die das Handeln selbst blockiert.

## Entwicklung

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest
```

Die Tests laufen offline gegen eine simulierte Binance-Börse (`tests/fakes.py`): Kauf und Positionsgröße, Stop, Ziel,
Zeit-Stop, Tageslimit, Notstopp, Ein- und Auszahlungen, Netzfehler nach ausgeführter Order, Absturz zwischen Order und
Buchung, Funktionstest und Telegram-Befehle.

| Datei | Inhalt |
|---|---|
| `strategy.py` | die Regel: Kennzahlen, Kaufsignal, Ausstiege (reine Rechnung) |
| `bot.py` | Hauptschleife, Kaufen, Verkaufen, Grenzen, Telegram-Befehle, `--check` |
| `exchange.py` | Binance über ccxt und eine Simulation mit derselben Schnittstelle (Papiermodus, Tests) |
| `state.py` · `notifier.py` · `config.py` | Gedächtnis (JSON) · Telegram · Einstellungen |
| `install.sh` · `deploy/` | Installation und systemd-Dienst |
