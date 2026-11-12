# Überblick: Was läuft, was kostet es, wie arbeitet der Bot?

Stand: 12.11.2026 (Version v3). Für alle, die den Bot bedienen, ohne den Code zu lesen.

## In einem Satz

Ein einziges Python-Programm auf deinem Server handelt über deinen Binance-Schlüssel mit zwei geprüften Regeln, meldet
sich über Telegram und benutzt **keine KI** – es entstehen keine KI-Kosten.

## Was auf dem Server läuft

| Dienst | Was er tut | Kosten |
|---|---|---|
| `newtry-bot` | der Bot selbst (`/root/newtry/bot.py`) | keine |
| `newtry-watchdog.timer` | alle 5 Minuten: Läuft der Bot? Lebt er? Platte voll? → Telegram-Alarm, Neustart höchstens 1× pro Stunde | keine |

Vom **alten Bot (azubiassist)** schaltet der NewTry-Installer diese Dienste ab: `trading-bot`, `trading-bot-watchdog`
(Dienst und Timer), `trading-dashboard`. Code und Daten bleiben in `/root/trading-bot` liegen, laufen aber nicht.

Nicht abgeschaltet wird `rclone-bot-speicher` (der Google-Drive-Speicher des alten Bots), falls du ihn damals
eingerichtet hast. Er kostet nichts und handelt nicht; abschalten mit `systemctl disable --now rclone-bot-speicher`.

## Welche Verbindungen es gibt

| Verbindung | Wofür | Kosten |
|---|---|---|
| **Binance** (über den Schlüssel in `/root/newtry/.env`) | Kurse, Kontostand, Kauf- und Verkaufsorders, Notbremse (Stop-Order an der Börse), optional Simple Earn | nur die Handelsgebühr: 0,10 % je Order, mit BNB 0,075 % |
| **Telegram** | Meldungen an dich, deine Befehle an den Bot | keine |
| Gemini, Claude, OpenAI | **werden nicht benutzt** | keine |

**Die KI des alten Bots ist aus.** Gemini und Claude wurden nur vom alten Hauptprogramm (`trading-bot`) aufgerufen
(Marktbeobachtung, Strategie-Vorschläge, Betriebsbericht; eingestellt waren bis zu 30 USD im Monat). Der NewTry-Installer
übernimmt aus der alten `.env` nur den Binance-Schlüssel, Telegram und die Währung – keine KI-Schlüssel.
Die KI-Schlüssel stehen aber noch in `/root/trading-bot/.env`. Empfehlung: in Google AI Studio und in der Anthropic-Konsole
löschen oder dort ein Ausgabenlimit von 0 setzen. Dann kann auch versehentlich nichts mehr kosten.

Laufende Kosten insgesamt: der Server (Hetzner) und die Handelsgebühren. Sonst nichts.

## Wie der Bot arbeitet

| Takt | Was passiert |
|---|---|
| alle 10 Sekunden | Telegram-Befehle lesen; Kurse der offenen Positionen prüfen: Stop, Ziel, Zeitablauf → verkaufen |
| jede Minute | Kontostand holen, Ein-/Auszahlungen erkennen, Bücher mit Binance abgleichen, Notbremsen prüfen, Verlustgrenzen, (wenn eingeschaltet) freies USDC in Simple Earn anlegen |
| alle 15 Minuten | **Crash-Kauf:** Ist ein großer Coin in 4 Stunden um 9 % oder mehr gefallen? → kaufen, nach 4 Stunden verkaufen |
| alle 4 Stunden (01, 05, 09, 13, 17, 21 Uhr) | **Trend:** Ist ein Coin über das Hoch der letzten 100 Vier-Stunden-Kerzen ausgebrochen und liegt über der EMA 200? → kaufen mit 1 % Risiko, Stop, Ziel, höchstens 20 Tage |
| täglich 9 Uhr | Tagesbericht, Prüfung des API-Schlüssels |
| am 1. des Monats | Monatsbericht |

Beide Regeln sind auf Binance-Kursen 2018–2026 geprüft (Walk-Forward, mit Kosten und Ausführungsverzögerung, 662
getestete Varianten). Bericht: `lab/ERGEBNISSE_V2.md`.

## Schutz

* **Notbremse an der Börse:** nach jedem Kauf eine Stop-Order direkt bei Binance – sie verkauft auch, wenn Bot oder Server ausfallen.
* **Notstopp:** fällt das Kapital 30 % (Standard v3; in älteren `.env` steht noch 40) unter den Höchststand, verkauft der Bot alles und hält an; `/weiter` erst nach 24 Stunden.
* **Fremde Bestände bleiben unangetastet:** Coins, die du selbst kaufst, rechnet der Bot nicht zu seinem Kapital und verkauft sie nie.
* **Wächter:** meldet, wenn Käufe schlechter laufen als simuliert, wenn eine Regel im Vorwärtstest abrutscht, wenn der Schlüssel auszahlen darf.

## Wo die Daten liegen

| Datei | Inhalt |
|---|---|
| `/root/newtry/.env` | Einstellungen und Schlüssel (nur für root lesbar) |
| `/root/newtry/data/state-live.json` | Gedächtnis: Positionen, Trades, Kapital-Verlauf (Papiermodus: `state-paper.json`) |
| `/root/newtry/data/bot.log` | Protokoll (auch: `journalctl -u newtry-bot`) |

## Was der Bot bewusst nicht tut – und warum

| Wunsch | Ergebnis der Prüfung |
|---|---|
| Den ganzen Tag handeln, viele Indikatoren, viele Coins | 640 Varianten auf 15m/1h: nach Gebühren fast alle negativ. Eine 15-Minuten-Kerze schwankt im Mittel 0,38 %, Hin- und Rückweg kosten 0,40 %. |
| Hebel | Auf der Kombi gerechnet (`lab/leverage.py`): 2020–2026 vervielfacht er den Ertrag, seit 2025 schadet er ab 2× (2×: +6 % statt +8 %/Jahr, 3×: −4 %, 5×: −37 % mit Zwangsliquidation). Rückgänge 47–97 %. |
| KI liest Nachrichten und handelt | Nicht nachweisbar: Es gibt keine historischen Nachrichtendaten zum Prüfen, und öffentliche Nachrichten sind im Kurs, bevor eine KI-Antwort da ist (Sekunden gegen Millisekunden). Der alte Bot hatte genau das – und hat nie einen Vorteil gezeigt. |
| Arbitrage | Preisunterschiede auf Binance werden von Hochfrequenz-Händlern in Millisekunden geschlossen; drei Orders kosten 0,225 % Gebühr. Mit 150 USDC und einem gewöhnlichen Mietserver ist das nicht zu gewinnen. |
| Copy-Trading-Spitzenreiter nachmachen | Simuliert (`lab/copy_luck.py`): Unter 2.000 Händlern ganz ohne Können erreicht in jedem zweiten Monat einer „+30 % in 30 Tagen bei unter 7,6 % Rückgang“. Die Spitzenreiter fallen im Folgemonat auf den Durchschnitt zurück; jeden Monat den Besten zu kopieren hätte 2020–2026 −16,5 % im Jahr gebracht. Prüfbar ist nur ein einzelner Trader mit vielen Trades (Zufallsvergleich). |
