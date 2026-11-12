# Überblick: Was läuft, was kostet es, wie arbeitet der Bot?

Stand: 12.11.2026 (Version v3.1). Für alle, die den Bot bedienen, ohne den Code zu lesen. Jede Aussage hier wurde von
einem unabhängigen Prüfagenten gegen den Code beider Projekte geprüft.

## In einem Satz

Ein einziges Python-Programm auf deinem Server handelt über deinen Binance-Schlüssel mit zwei geprüften Regeln, meldet
sich über Telegram und benutzt **keine KI**. Aus dem alten Projekt läuft aber noch **eine** KI-Sache weiter – nicht auf
dem Server, sondern in deinem Claude-Konto (siehe unten).

## Was auf dem Server läuft

| Dienst | Was er tut | Kosten |
|---|---|---|
| `newtry-bot` | der Bot selbst (`/root/newtry/bot.py`) | keine |
| `newtry-watchdog.timer` | alle 5 Minuten: Läuft der Bot? Lebt er (Lebenszeichen höchstens 10 Minuten alt)? Platte ab 90 % voll? → Telegram-Alarm, Neustart höchstens 1× pro Stunde | keine |

Vom **alten Bot (azubiassist)** schaltet der NewTry-Installer diese Dienste ab – erst nachdem die Startklar-Prüfung
bestanden ist: `trading-bot`, `trading-bot-watchdog` (Dienst und Timer), `trading-dashboard`. Code und Daten bleiben in
`/root/trading-bot` liegen, laufen aber nicht. Der Update-Agent des alten Bots war kein eigener Dienst, sondern lief im
alten Hauptprogramm – mit `trading-bot` ist er ebenfalls aus. Liegen bleiben (falls damals eingerichtet):
`/root/trading-bot-src`, `/root/trading-bot-staging`, der Deploy-Schlüssel `/root/.ssh/azubiassist_deploy` und ein
GitHub-Token (`GITHUB_TASK_TOKEN` in der alten `.env`). Empfehlung: Token und Deploy-Schlüssel bei GitHub widerrufen.

Nicht abgeschaltet wird `rclone-bot-speicher` (der Google-Drive-Speicher des alten Bots), falls du ihn damals
eingerichtet hast. Er handelt nicht und ruft keine KI auf; die alten Sicherungen belegen aber weiter Platz in deinem
Google Drive. Abschalten: `systemctl disable --now rclone-bot-speicher`.

## Welche Verbindungen es gibt

| Verbindung | Wofür | Kosten |
|---|---|---|
| **Binance** (über den Schlüssel in `/root/newtry/.env`) | Kurse, Kontostand, Kauf- und Verkaufsorders, Notbremse (Stop-Order an der Börse), optional Simple Earn | die Handelsgebühr: 0,10 % je Order, mit BNB 0,075 % (Standardstufe), dazu Spread und Schlupf |
| **Telegram** | Meldungen an dich, deine Befehle an den Bot | keine |
| Gemini, Claude, OpenAI | **werden vom Bot nicht benutzt** | keine |

**Die KI des alten Bots auf dem Server ist aus.** Gemini und Claude wurden nur vom alten Hauptprogramm (`trading-bot`)
aufgerufen (Marktbeobachtung, Strategie-Vorschläge, Betriebsbericht, Code-Prüfung des Update-Agenten). Voreingestellt war
ein Monatsbudget von 30 USD – nur eine **Warnschwelle**, keine harte Grenze. Der NewTry-Installer übernimmt aus der alten
`.env` nur Binance-Schlüssel, Telegram und die Währung – keine KI-Schlüssel. Die KI-Schlüssel stehen aber noch in
`/root/trading-bot/.env`. Empfehlung: in Google AI Studio und in der Anthropic-Konsole löschen oder ein Ausgabenlimit von 0
setzen. Dann kann auch versehentlich nichts mehr kosten.

**Noch aktiv: der „Ingenieur-Agent (Trading-Bot azubiassist)“** – eine geplante Claude-Code-Aufgabe in deinem
Claude-Konto, jeden Sonntag 11:23 Uhr (zuletzt am 08.11.2026, 17 Sekunden). Er sucht im alten Repository nach offenen
Aufgaben des alten Bots. Da der alte Bot aus ist, kommen keine neuen dazu, und er beendet sich jedes Mal sofort. Er läuft
über das Kontingent deines Claude-Plans, nicht über einen API-Schlüssel. Abschalten: in claude.ai bei den geplanten
Aufgaben, oder Claude in einer Sitzung darum bitten.

**Laufende Kosten insgesamt:** der Server (Hetzner) und die Handelsgebühren (plus Spread und Schlupf). Solange er
eingeschaltet ist, dazu der wöchentliche Ingenieur-Agent (Kontingent deines Claude-Plans); falls eingerichtet, der
Google-Drive-Platz der alten Sicherungen.

## Wie der Bot arbeitet

| Takt | Was passiert |
|---|---|
| alle 10 Sekunden | Telegram-Befehle lesen; Kurse der offenen Positionen prüfen: Stop, Ziel, Zeitablauf → verkaufen |
| jede Minute | Kontostand holen, Ein-/Auszahlungen erkennen, Bücher mit Binance abgleichen, Notbremsen prüfen, Verlustgrenzen. Nur mit Echtgeld und wenn eingeschaltet: freies USDC über der Reserve (60 USDC, mindestens 30 % des Kapitals; ab 10 USDC) in Simple Earn anlegen |
| alle 15 Minuten | **Crash-Kauf:** Schließt ein großer Coin mindestens 9 % unter dem Schluss 4 Stunden davor? → kaufen, nach 4 Stunden verkaufen (Notstop −15 %) |
| alle 4 Stunden, ca. 20 Sekunden nach Kerzenschluss | **Trend:** Ist ein Coin über das Hoch der letzten 100 Vier-Stunden-Kerzen ausgebrochen und liegt über der EMA 200? → kaufen mit 1 % Risiko, Stop, Ziel, höchstens 20 Tage. Uhrzeiten: Winterzeit 01, 05, 09, 13, 17, 21 Uhr; Sommerzeit 02, 06, 10, 14, 18, 22 Uhr |
| täglich 9 Uhr | Tagesbericht; mit Echtgeld Prüfung des API-Schlüssels |
| am 1. des Monats | Monatsbericht (der erste nach einem Update umfasst nur die Zeit ab dem ersten Tagesbericht danach und sagt das) |

Beide Regeln sind auf Binance-Kursen 2018–2026 geprüft: die eingesetzte Einstellung fest gerechnet mit 0,20 % Kosten je
Seite und Kauf 1 Minute nach dem Signal, die Regel-Familien zusätzlich im Walk-Forward, 662 getestete Varianten
insgesamt. Berichte: `lab/ERGEBNISSE_V2.md` und `lab/ERGEBNISSE_V2B.md`.

## Schutz

* **Notbremse an der Börse:** nach jedem Kauf eine Stop-Order direkt bei Binance. Sie verkauft auch, wenn Bot oder Server
  ausfallen – sofern der Kurs nicht mehr als 3 % unter den Auslöser springt (Stop-Limit-Order mit Mindestpreis).
* **Notstopp:** fällt das Kapital 30 % unter den Höchststand, verkauft der Bot alles und hält an; `/weiter` erst nach 24
  Stunden. In älteren `.env` steht noch 40 (oder 25) – das Update stellt beides von selbst auf 30.
* **Ein- und Auszahlungen** zählen nie als Gewinn oder Verlust. Bei einer Auszahlung sinkt der Höchststand im selben
  Verhältnis wie das Kapital; der Rückgang in Prozent bleibt gleich, eine Auszahlung löst also nie den Notstopp aus.
  (Bis v3 konnte eine Auszahlung während eines Rückgangs den Notstopp auslösen – behoben in v3.1.)
* **Fremde Bestände:** Coins, die du selbst kaufst, rechnet der Bot nicht zu seinem Kapital und verkauft sie nie. Aber:
  Jedes USDC im Spot-Konto zählt als sein Kapital (gibst du USDC für einen eigenen Coin-Kauf aus, ist das für ihn eine
  Auszahlung), und BNB wird für Gebühren verbraucht. Mit Simple Earn rechnet er nur, was **er** dort angelegt hat.
* **Wächter:** meldet und setzt den Crash-Kauf aus, wenn Käufe schlechter laufen als simuliert; meldet, wenn eine Regel
  im Vorwärtstest abrutscht und wenn der Schlüssel auszahlen darf.

## Wo die Daten liegen

| Datei | Inhalt |
|---|---|
| `/root/newtry/.env` | Einstellungen und Schlüssel (nur für root lesbar) |
| `/root/newtry/data/state-live.json` | Gedächtnis: Positionen, Trades, Kapital-Verlauf (Papiermodus: `state-paper.json`) |
| `/root/newtry/data/bot.log` | Protokoll (auch: `journalctl -u newtry-bot`) |

## Was der Bot bewusst nicht tut – und warum

| Wunsch | Ergebnis der Prüfung |
|---|---|
| Den ganzen Tag handeln, viele Indikatoren, viele Coins | 640 Varianten auf 15m/1h (mit 0,15 % Kosten je Seite): nach Gebühren fast alle negativ. Eine 15-Minuten-Kerze bewegt sich vom Anfang bis zum Ende im Mittel um 0,31 % (seit 2025: 0,25 %); Hin- und Rückweg kosten mit Spread und Schlupf rund 0,4 % (reine Gebühr 0,15–0,2 %). |
| Hebel | Auf der Kombi gerechnet (`lab/leverage.py`, 8 % Zins): 2020–10/2026 vervielfacht er den Ertrag (2×: +179 % statt +80 % im Jahr), aber auch die Rückgänge (2×: 47 %, 3×: 63 %, 5×: 97 % mit einer Zwangsliquidation im Mai 2021). Seit 2025: 1,5× +8 %, 2× +6 %, 3× −4 %, 5× −37 % im Jahr statt +8 %. Mit dem 30-%-Notstopp gerechnet (frischer Start 2025) liegt 2× je nach Pause zwischen +1 % und +7 % im Jahr, 3× zwischen +11 % und +24 % – aber mit 6 Notstopps in 22 Monaten und über 50 % Rückgang. Das Ergebnis kippt mit kleinen Annahmen; ein verlässlicher Vorteil ist nicht erkennbar (`lab/ERGEBNISSE_V3.md`). |
| KI liest Nachrichten und handelt | Nicht nachweisbar: Im Projekt gibt es keine historischen Nachrichtendaten zum Prüfen, und öffentliche Nachrichten sind im Kurs, bevor eine KI-Antwort da ist (Sekunden gegen Millisekunden). Der alte Bot hatte genau das, hat aber nie gehandelt – ein Vorteil wurde nie gemessen. Der Crash-Kauf ist die messbare Form davon: Er reagiert auf die Wirkung schlechter Nachrichten (Zufallsvergleich bestanden, p = 0,003). |
| Arbitrage | Preisunterschiede auf Binance werden von Hochfrequenz-Händlern in Millisekunden geschlossen; drei Orders kosten 0,225 % Gebühr mit BNB, 0,30 % ohne. Mit wenigen hundert USDC und einem gewöhnlichen Mietserver ist das nicht zu gewinnen. |
| Copy-Trading-Spitzenreiter nachmachen | Simuliert (`lab/copy_luck.py`): Unter 2.000 Händlern ganz ohne Können erreicht in jedem zweiten Monat einer „+30 % in 30 Tagen bei unter 7,6 % Rückgang“. Die Spitzenreiter fallen im Folgemonat auf den Durchschnitt zurück; jeden Monat den Besten zu kopieren hätte 2020–2026 −16,5 % im Jahr gebracht. Prüfbar ist nur ein einzelner Trader mit vielen Trades (Zufallsvergleich). |
