# NewTry – schlanker Handelsbot für Binance Spot

Ein Neuanfang nach *azubiassist*: zwei auf echten Binance-Kursen 2017–2026 geprüfte Regeln, harte Verlustgrenzen, und er
**handelt wirklich**. Er übernimmt Binance- und Telegram-Schlüssel automatisch vom alten Bot auf dem Server.
Wie die Regeln ausgewählt wurden (640 Daytrading-Varianten, Trend, Momentum, Härtetests), steht mit allen Zahlen in
**[research/ERGEBNISSE.md](research/ERGEBNISSE.md)**. Die zweite Forschungsrunde hat beide Projekte zusammengeführt und
alle Kandidaten (515 Varianten, neue Strategiefamilien, die Gemini-Vorschläge) unter identischen, realistischen
Bedingungen verglichen: **[lab/ERGEBNISSE_V2.md](lab/ERGEBNISSE_V2.md)**. Ergebnis: Diese beiden Regeln bleiben.
Hebel und Copy-Trading-Ranglisten: **[lab/ERGEBNISSE_V3.md](lab/ERGEBNISSE_V3.md)**. Was auf dem Server läuft, welche
Verbindungen es gibt und was es kostet: **[UEBERBLICK.md](UEBERBLICK.md)**.

## Was er macht

| | ① Trend | ② Crash-Kauf |
|---|---|---|
| **Kauf** | eine 4h-Kerze schließt über dem Hoch der vorherigen 100 Kerzen und über der EMA 200 | ein großer Coin fällt binnen 4 Stunden um 9 % oder mehr (Prüfung alle 15 Minuten) |
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
| **Notbremse bei Binance** | nach jedem Kauf | eine Stop-Order liegt **direkt an der Börse**, 1 % unter dem Stop des Bots. Sie verkauft auch dann, wenn Bot, Server oder Internet ausfallen – sofern der Kurs nicht mehr als 3 % unter den Auslöser springt (es ist eine Stop-Limit-Order mit Mindestpreis). Läuft der Bot, verkauft er selbst zuerst und storniert sie vorher. |
| **Wächter** | alle 5 Minuten | meldet per Telegram, wenn der Bot nicht läuft, hängt oder die Festplatte voll ist, und startet ihn neu (höchstens einmal pro Stunde) |
| Notstopp | −30 % vom Höchststand | **alles verkaufen und anhalten**; `/weiter` erst nach 24 Stunden Wartezeit, damit der Neustart eine Entscheidung ist und keine Reaktion (der größte Rückgang im Rückblick: 26–28 %). Wird die Grenze gesenkt, während der Rückgang schon darüber liegt, gilt die alte weiter, bis er darunter fällt – die Umstellung selbst löst nie einen Notverkauf aus. |
| Zinsen auf Cash | aus (`EARN_ENABLED`) | der Bot ist im Mittel nur zu etwa 27 % investiert. Eingeschaltet legt er freies USDC über einer **Reserve** (60 USDC, mindestens 30 % des Kapitals – genug für einen Crash-Kauf ohne Rücknahme) in Binance Simple Earn Flexible an (3–9 % im Jahr, schwankend) und holt es vor einem Kauf zurück. Er führt ein eigenes Hauptbuch: Nur was **er** anlegt, zählt zu seinem Kapital; dein eigenes Earn-Guthaben bleibt unberührt. Eine Rücknahme, die noch unterwegs ist, zählt bis zu 6 Stunden weiter zum Kapital (keine Auszahlung); danach gilt, was Binance zeigt. Dauert sie länger als 20 Sekunden, kauft er mit der Reserve. Ausschalten holt sein Guthaben von selbst zurück. Risiken: verzögerte Rücknahme bei extremer Marktlage, Gegenpartei Binance. |
| Einzahlungen | automatisch | werden erkannt, sofort ins Kapital gerechnet (Positionsgröße, Notstopp-Höchststand) und ab der nächsten Prüfung gehandelt; sie zählen nie als Gewinn |
| Sperre nach Notstop | 24 h je Coin (Crash-Kauf) | ein Coin, der wie LUNA auf null fällt, wird nicht immer wieder nachgekauft |
| Crash-Käufe gleichzeitig | höchstens 3 | im marktweiten Crash (März 2020) nie mehr als 60 % des Kapitals im Fall |
| Tageslimit | aus | würde genau die Crash-Käufe blockieren; einschaltbar mit `DAILY_LOSS_LIMIT_PCT` |
| Doppelte Orders | ausgeschlossen | jede Order hat eine eigene Nummer; nach Netzfehler oder Absturz wird bei Binance nachgesehen, bevor neu gehandelt wird |
| Ein-/Auszahlungen | erkannt | zählen weder als Gewinn noch als Verlust. Der Höchststand ändert sich bei jeder Ein- und Auszahlung im selben Verhältnis wie das Kapital – der Rückgang in Prozent bleibt gleich: Eine Auszahlung löst nie den Notstopp aus, und Hin und Her schwächt ihn nie ab. Auch USDC, das du selbst für einen Coin-Kauf ausgibst, ist für den Bot eine Auszahlung. |
| Fremde Bestände | unangetastet | der Bot verkauft nur Coins, die er selbst gekauft hat. Aber: Jedes USDC im Spot-Konto zählt als sein Kapital, und BNB wird für Gebühren verbraucht. |
| Ausführungswächter | jeder Kauf | misst, ob der Bot so günstig kauft wie die Simulation (Kaufkurs gegen den Signal-Schluss). Kauft er im Crash über 10 Käufe deutlich schlechter, wird **nur der Crash-Kauf** ausgesetzt – sein Vorteil wäre dann aufgezehrt. Weiter mit `/weiter`. |
| Vorwärtstest | nach jedem Verkauf | vergleicht die letzten 30 Trades je Regel mit dem Rückblick und meldet, wenn es schlechter läuft als in 95 % aller vergangenen Phasen (nur Meldung) |
| Schlüssel-Prüfung | täglich (Echtgeld) | warnt, wenn der API-Schlüssel auszahlen darf oder nicht mehr handeln darf |
| Funktionstest | einmal beim ersten Echtgeld-Start | Kauf und sofortiger Verkauf für ca. 7 USDC beweisen, dass Schlüssel und Orders funktionieren (Kosten: wenige Cent) |

## Ehrliche Erwartung

* **Rückblick, realistisch gerechnet** (2018–10/2026, Kauf 1 Minute nach Kerzenschluss, Rückgang in jeder 15m-Kerze,
  doppelte Kosten 0,30 % je Seite): **+60 % pro Jahr**, größter Rückgang **28 %**. Die früher genannten +77 % enthielten
  2017 (mit einem nicht handelbaren Fehlprint) und Käufe in der Sekunde des Kerzenschlusses
  ([Überleitung](lab/ERGEBNISSE_V2.md#3-prüfung-der-vorhandenen-backtests)).
* **Viel handeln kostet Geld:** Ein Bot, der seit 01/2025 den ganzen Tag gehandelt hätte (10–36 Trades am Tag), hätte aus
  159,69 USDC nach Gebühren **0 bis 0,57 USDC** gemacht. NewTry im selben Zeitraum: 216,59 USDC (`research/active.py`).
* **Das ist ein bestmöglicher Fall.** Coins, die gestorben sind, fehlen im Datensatz. Die großen Jahre (2020, 2021, 2024)
  waren Bullenmärkte.
* **Seit Anfang 2025 lief es zäh:** realistisch gerechnet etwa **+8 % pro Jahr**. Wer jetzt startet, startet in genau so
  einer Phase. Der Crash-Kauf lag 2025/26 im Schnitt bei ≈ 0 je Trade – darum der Ausführungswächter.
* 35 % der Monate waren im Minus, der schlechteste mit −15 % (2020–10/2026, realistisch gerechnet). Rückgänge von 25–40 % muss man aushalten können.
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
| `/status` | Kapital, Gewinn seit Start, offene Positionen mit Stop und Ziel, Grenzen, angelegtes Guthaben und Zinsen |
| `/warum` | jede Entscheidung der letzten 24 Stunden in einem Satz: Signale, Käufe, Ablehnungen, Verkäufe |
| `/erwartung` | was in 30 Tagen statistisch zu erwarten ist – als Spanne aus der Simulation, auf dein Kapital umgerechnet |
| `/markt` | wie weit jeder Coin vom Kaufsignal entfernt ist |
| `/trades` | die letzten abgeschlossenen Trades |
| `/pause` · `/weiter` | keine neuen Käufe bzw. wieder kaufen (`/weiter` hebt auch den Notstopp auf) |
| `/notverkauf` | alle Positionen sofort verkaufen (mit Bestätigung `/notverkauf_ja`) |

Dazu kommen von selbst: jeder Kauf und Verkauf, jeder Einbruch ab −9 % (⚡, mit Ergebnis), eine stille Meldung nach jeder
4h-Prüfung, der Tagesbericht um 9 Uhr, am 1. jedes Monats der **Monatsbericht** (Einzahlungen, Handelsergebnis, Gebühren,
Zinsen, Vergleich mit BTC halten) und Warnungen (Binance länger nicht erreichbar, Schlüssel abgelehnt, Notstopp).

## Auf dem Server

| Was | Befehl |
|---|---|
| Läuft er? | `systemctl is-active newtry-bot` |
| Live-Protokoll (Ende mit Strg+C) | `journalctl -u newtry-bot -f` |
| Anhalten | `systemctl disable --now newtry-bot` (nur `stop` reicht nicht – dann startet ihn der Wächter neu) |
| Wieder starten | `systemctl enable --now newtry-bot` |
| Läuft der Wächter? | `systemctl list-timers newtry-watchdog.timer` |
| Startklar-Prüfung | `cd /root/newtry && .venv/bin/python bot.py --check` |
| Papier ↔ Echtgeld | `bash /root/newtry-install.sh --paper` / `bash /root/newtry-install.sh --live` |
| Neue Binance-Schlüssel | `bash /root/newtry-install.sh --keys` |
| Einstellungen ändern | `nano /root/newtry/.env`, danach `systemctl restart newtry-bot` |
| Zurück zum alten Bot | `systemctl disable --now newtry-bot newtry-watchdog.timer && systemctl enable --now trading-bot` – vorher in der Binance-App die offenen Notbremsen (Stop-Orders) prüfen |

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
ausgeführter Order, Absturz zwischen Order und Buchung, Funktionstest, Telegram-Befehle, die Notbremse (setzen, vor dem
eigenen Verkauf stornieren, Auslösen während der Bot aus ist, Kurslücke, Teilausführung, in der App storniert, Netzfehler beim
Setzen, Neustart) und der Wächter (mit nachgebautem systemd). `tests/test_binance_ccxt.py` prüft mit dem echten ccxt-Code und
Antworten im Binance-Format, welche Anfragen bei Binance ankämen.

Zusätzlich wurde der Bot-Code mit echten Kursen (07–09/2024 und 05–06/2021) gegen die Forschungs-Simulation geprüft:
Trade für Trade dieselben Käufe, mit und ohne Notbremse. Und ein Ausfall-Test (`research/outage.py`): Der Bot fällt am
19.05.2021 für 24 Stunden aus, mitten im Crash. BCH fiel in der Zeit um bis zu 55 %, die Notbremse bei Binance hat bei −11 %
verkauft, und nach dem Neustart war alles richtig gebucht.

| Datei | Inhalt |
|---|---|
| `strategy.py` | die beiden Regeln: Kennzahlen, Kaufsignale, Ausstiege (reine Rechnung) |
| `guards.py` | Wächter: Ausführung, Vorwärtstest, Schlüssel-Prüfung (reine Rechnung, Referenzwerte aus `lab/`) |
| `research/` | Forschungsrunde 1: Datenprüfung, alle Auswertungen und der Ergebnisbericht `ERGEBNISSE.md` |
| `lab/` | Forschungsrunde 2: gemeinsamer Maßstab (`MASSSTAB.md`), Simulationsmaschine, alle Familien, Bericht `ERGEBNISSE_V2.md` |
| `bot.py` | Hauptschleife, Kaufen, Verkaufen, Grenzen, Telegram-Befehle, `--check` |
| `exchange.py` | Binance über ccxt und eine Simulation mit derselben Schnittstelle (Papiermodus, Tests) |
| `state.py` · `notifier.py` · `config.py` | Gedächtnis (JSON) · Telegram · Einstellungen |
| `install.sh` · `deploy/` | Installation und systemd-Dienst |
