# NewTry – schlanker Handelsbot für Binance Spot

Ein Neuanfang nach *azubiassist*: zwei auf echten Binance-Kursen 2017–2026 geprüfte Regeln, harte Verlustgrenzen, und er
**handelt wirklich**. Er übernimmt Binance- und Telegram-Schlüssel automatisch vom alten Bot auf dem Server.
Wie die Regeln ausgewählt wurden (640 Daytrading-Varianten, Trend, Momentum, Härtetests), steht mit allen Zahlen in
**[research/ERGEBNISSE.md](research/ERGEBNISSE.md)**.

## Was er macht

| | ① Trend | ② Crash-Kauf |
|---|---|---|
| **Kauf** | eine 4h-Kerze schließt über dem Hoch der vorherigen 100 Kerzen und über der EMA 200 | ein großer Coin fällt binnen 4 Stunden um 10 % oder mehr (Prüfung alle 15 Minuten) |
| **Größe** | 1 % Risiko bis zum Stop (bei 150 USDC meist 20–50 USDC), höchstens 33 % | 20 % des Kapitals |
| **Verkauf** | Stop 2 ATR · Ziel 15 ATR · spätestens nach 20 Tagen | nach 4 Stunden · Notstop 15 % unter dem Einstieg |
| **Höchstens** | 3 Positionen | 3 Positionen; nach einem Notstop 24 h Sperre für diesen Coin |
| **Coins** | 25 (ohne USDC-Markt werden übersprungen) | BTC, ETH, SOL, BNB, XRP, TRX, DOGE, ZEC, ADA, BCH |
| **Gefühl** | nur jeder 3. bis 4. Trade gewinnt, die Gewinner sind groß (bis +70 %) | 6 von 10 gewinnen, meist ein paar Prozent |

Gemeinsam: je Coin nur eine Position, gekauft wird nur mit freiem Guthaben, Stop/Ziel/Verkaufszeit werden alle 10 Sekunden
geprüft. Die beiden Regeln verdienen zu verschiedenen Zeiten (Trend in Aufwärtsphasen, Crash-Kauf auch in Bärenjahren wie
2018 und 2022) – zusammen gab es im Rückblick nur ein Verlustjahr statt drei. **KI** ist bewusst nicht im Handelsweg:
keine API-Kosten, keine erfundenen Antworten, jede Entscheidung nachrechenbar.

## Schutz für dein Geld

| Grenze | Standard | Wirkung |
|---|---|---|
| Notstopp | −40 % vom Höchststand | **alles verkaufen und anhalten**, weiter nur mit `/weiter` (der größte Rückgang im Rückblick: 26 %) |
| Sperre nach Notstop | 24 h je Coin (Crash-Kauf) | ein Coin, der wie LUNA auf null fällt, wird nicht immer wieder nachgekauft |
| Crash-Käufe gleichzeitig | höchstens 3 | im marktweiten Crash (März 2020) nie mehr als 60 % des Kapitals im Fall |
| Tageslimit | aus | würde genau die Crash-Käufe blockieren; einschaltbar mit `DAILY_LOSS_LIMIT_PCT` |
| Doppelte Orders | ausgeschlossen | jede Order hat eine eigene Nummer; nach Netzfehler oder Absturz wird bei Binance nachgesehen, bevor neu gehandelt wird |
| Ein-/Auszahlungen | erkannt | zählen weder als Gewinn noch als Verlust und lösen keinen Notstopp aus |
| Fremde Bestände | unangetastet | der Bot verkauft nur, was er selbst gekauft hat |
| Funktionstest | einmal beim ersten Echtgeld-Start | Kauf und sofortiger Verkauf für ca. 7 USDC beweisen, dass Schlüssel und Orders funktionieren (Kosten: wenige Cent) |

## Ehrliche Erwartung

* **Rückblick** 08/2017–10/2026, 10 Coins, mit doppelt so hohen Kosten wie normal: **+75 % pro Jahr**, größter Rückgang
  **26 %**, ein Verlustjahr. Auf den bei der Auswahl nicht benutzten Daten 2023–2026: +52 % pro Jahr.
* **Das ist ein bestmöglicher Fall.** Coins, die gestorben sind, fehlen im Datensatz. Die großen Jahre (2020, 2021, 2024)
  waren Bullenmärkte.
* **Seit Anfang 2025 lag die Kombination bei etwa ±0** (+3,5 % pro Jahr, 2026 bis Oktober −7 %). Wer jetzt startet,
  startet in genau so einer Phase.
* 38 % der Monate waren im Minus, der schlechteste mit −11,6 %. Rückgänge von 25–40 % muss man aushalten können.
* Mit rund 150 € Einsatz bedeutet selbst ein sehr gutes Jahr ein paar Dutzend bis wenige hundert Euro. Setze nur Geld ein,
  dessen Verlust du verkraftest.

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

Dazu kommen von selbst: jeder Kauf und Verkauf, jeder Einbruch ab −10 % (⚡, mit Ergebnis), eine stille Meldung nach jeder
4h-Prüfung, der Tagesbericht um 9 Uhr und Warnungen (Binance länger nicht erreichbar, Schlüssel abgelehnt, Notstopp).

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
verhindert haben. NewTry hat zwei geprüfte Regeln und feste Grenzen, aber keine Hürde, die das Handeln selbst blockiert.

## Entwicklung

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest
```

Die Tests laufen offline gegen eine simulierte Binance-Börse (`tests/fakes.py`): Kauf und Positionsgröße, Stop, Ziel,
Zeit-Stop, Crash-Kauf mit 4-Stunden-Ausstieg und Sperre, Tageslimit, Notstopp, Ein- und Auszahlungen, Netzfehler nach
ausgeführter Order, Absturz zwischen Order und Buchung, Funktionstest und Telegram-Befehle. Zusätzlich wurde der Bot-Code mit
echten Kursen (07–09/2024 und 05–06/2021) gegen die Forschungs-Simulation geprüft: Trade für Trade dieselben Käufe.

| Datei | Inhalt |
|---|---|
| `strategy.py` | die beiden Regeln: Kennzahlen, Kaufsignale, Ausstiege (reine Rechnung) |
| `research/` | Datenprüfung, alle Auswertungen und der Ergebnisbericht `ERGEBNISSE.md` |
| `bot.py` | Hauptschleife, Kaufen, Verkaufen, Grenzen, Telegram-Befehle, `--check` |
| `exchange.py` | Binance über ccxt und eine Simulation mit derselben Schnittstelle (Papiermodus, Tests) |
| `state.py` · `notifier.py` · `config.py` | Gedächtnis (JSON) · Telegram · Einstellungen |
| `install.sh` · `deploy/` | Installation und systemd-Dienst |
