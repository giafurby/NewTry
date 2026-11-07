# Strategie-Forschung: Was auf echten Binance-Kursen 2017–2026 funktioniert hat

Stand: 07.11.2026. Alle Zahlen lassen sich mit den Skripten in diesem Ordner nachrechnen (Anleitung ganz unten).

## Kurz

* **Allgemeines Daytrading verliert.** Nach Gebühren verlieren Rücksetzer-, Ausbruchs- und RSI-Regeln auf 15-Minuten- und
  1-Stunden-Kerzen fast immer. Selbst „einfach kaufen und ein paar Stunden halten“ kostet −0,2 bis −0,3 % je Trade.
* **Eine Ausnahme: nach einem Crash kaufen.** Fällt ein großer Coin innerhalb von 4 Stunden um 10 % oder mehr, federte der
  Kurs in den folgenden 4 Stunden meist zurück (Zwangsliquidationen). Das funktionierte auch in den Bärenjahren 2018 und 2022.
* **Trendfolge auf 4h-Kerzen** (die Regel aus dem alten Projekt) war die stabilste Einzelstrategie.
* **Beide zusammen** sind praktisch unkorreliert (Korrelation der Tagesrenditen ≈ 0). Kombiniert halbiert sich die Zahl der
  Verlustjahre, und die Rendite steigt deutlich, bei gleichem größtem Rückgang.
* **Ehrlich:** Seit Anfang 2025 lag auch die Kombination nur bei etwa ±0. Der Rückblick ist ein bestmöglicher Fall.

## Daten

| | |
|---|---|
| Quelle | [Speirsy11/crypto-dataset](https://github.com/Speirsy11/crypto-dataset) (CC0), gebaut aus den öffentlichen 1-Minuten-Daten von Binance |
| Coins | BTC, ETH, SOL, BNB, XRP, TRX, DOGE, ZEC, ADA, BCH (jeweils gegen USDT), 17.08.2017 bis 30.10.2026 |
| Umfang | 2.925 Monatsdateien (15 Minuten, 1 Stunde, 1 Tag), jede gegen ihre SHA-256-Prüfsumme geprüft |
| Echtheit | 10 von 11 bekannten Binance-Hochs/-Tiefs stimmen auf den Cent (z. B. BTC 69.000,00 am 10.11.2021, 3.782,13 am 13.03.2020). Die 15m-, 1h- und Tagesdaten passen exakt zueinander. Die rund 40 Lücken je Coin sind Binance-Wartungen. |
| Kosten | 0,10 % Gebühr + 0,05 % Schlupf = **0,15 % je Seite**; Härtetest mit 0,30 % und 0,50 % |
| Aufteilung | Auswahl der Einstellungen nur auf **2017–2022**, Prüfung auf **2023–10/2026** (bei der Auswahl nicht benutzt) |

## 1. Daytrading (640 Varianten, `daytrade.py`)

Getestet auf 15m und 1h, alle Coins gepoolt: RSI(2)/RSI(14)-Rücksetzer, Bollinger-Band, N-Kerzen-Ausbruch mit Volumen,
Einbruch um X % in M Kerzen; jeweils mit/ohne Trendfilter, 4–32 Kerzen Haltedauer, mit/ohne Stop.

| Vergleich | Ergebnis je Trade nach Kosten (15m) |
|---|---|
| In jeder Kerze kaufen, 1–8 h halten | −0,22 % bis −0,29 % (das ist der Preis des Daytradings) |
| Die besten Varianten auf 2017–2022 | fast alle aus der Familie „Einbruch kaufen“ (+1 bis +2,8 %), auch 2023–2026 positiv |

## 2. Härtetest „Einbruch kaufen“ (`dip.py`, `dip_stress.py`)

Als Depot mit nur einer Position je Coin. Die beiden Kandidaten im Vergleich:

| | −5 % in 1 h, 8 h halten | −8 % in 4 h, 4 h halten |
|---|---|---|
| Ohne die 20 besten von 780 bzw. 570 Crash-Tagen | +0,07 % je Trade (hängt an Glückstagen) | +0,25 % je Trade (hält) |
| Jahre im Plus (0,30 % Kosten, Notstop −15 %) | 7 von 10, 2022: −33 % | 8 von 10, schlechtestes Jahr −1 % |
| Ergebnis | **verworfen** | weiterverfolgt |

## 3. Trendfolge und Momentum (`trend.py`, Kosten 0,30 % je Seite)

| Strategie | 2017–2022 Ertrag/Jahr · größter Rückgang | 2023–2026 Ertrag/Jahr · größter Rückgang |
|---|---|---|
| BTC halten | +29 % · 83 % | +50 % · 53 % |
| Alle Coins gleich gewichtet halten | +70 % · 86 % | +60 % · 52 % |
| Trendfilter Tages-SMA 50, je Coin 1/10 | +74 % · 55 % | +40 % · 38 % |
| Momentum-Rotation 60 Tage, Top 3 | +49 % · 78 % | +120 % · 43 % |
| Momentum-Rotation 14 Tage, Top 1 | +61 % · **94 %** | +268 % · 65 % |
| **4h-Ausbruch 100 Kerzen + EMA 200, Stop 2 ATR, Ziel 15 ATR, 20 Tage, 1 % Risiko, max. 3** | **+45 % · 26 %** | **+45 % · 24 %** |

Momentum bringt in Bullenjahren riesige Renditen, aber Rückgänge bis 94 %: Das widerspricht dem Ziel „nicht pleite“.
Der 4h-Ausbruch war in beiden Abschnitten gleich gut. Jede Abwandlung (Ausbruch 50/200 Kerzen, Stop 3 ATR, Ziel 8/12 ATR,
Zeit-Stop 40 Kerzen) war schlechter oder schwankungsreicher.

## 4. Die Kombination in einem Depot (`combo.py`, `robust.py`, `risk.py`, `final.py`)

Simulation auf 15-Minuten-Basis wie im Bot: gemeinsames Kapital, je Coin nur eine Position, Kauf nur mit freiem Geld.

**Endgültige Einstellung:** Trend 1 % Risiko, max. 3 · Crash-Kauf ab −10 % in 4 h, 20 % je Kauf, max. 3, Notstop −15 %,
nach 4 h raus, 24 h Sperre nach Notstop.

| Kosten 0,30 % je Seite | Ertrag/Jahr | größter Rückgang | 2023–2026 | Verlustjahre |
|---|---|---|---|---|
| nur Trend | +45 % | 26 % | +45 % | 3 (2018 −7 %, 2022 −14 %, 2026 −0 %) |
| nur Crash-Kauf | +23 % | 15 % | +6 % | 1 |
| **beide (final)** | **+75 %** | **26 %** | **+52 %** | **1 (2026 bis Oktober: −7 %)** |

Pro Jahr (final): 2017 +80 % · 2018 +16 % · 2019 +42 % · 2020 +182 % · 2021 +262 % · 2022 +15 % · 2023 +97 % ·
2024 +135 % · 2025 +15 % · 2026 −7 %. Schlechtester Monat −11,6 % (Februar 2025), 38 % der Monate im Minus.

**Stabilität** (jeweils nur eine Einstellung geändert):

| Änderung | Ertrag/Jahr | größter Rückgang |
|---|---|---|
| Crash-Schwelle −9 % / −12 % / −15 % | +77 % / +71 % / +65 % | 25 % / 25 % / 23 % |
| Haltedauer 2 h / 8 h | +81 % / +74 % | 26 % / 28 % |
| Notstop −10 % / −20 % | +60 % / +75 % | 25 % / 28 % |
| Crash-Kauf nur BTC, ETH, SOL, BNB, XRP | +72 % | 24 % |
| Kosten 0,15 % / 0,50 % je Seite | +91 % / +55 % | 25 % / 30 % |
| Trend 1,5 % Risiko (aggressiver) | +92 % | 32 % |
| bis zu 5 statt 3 Crash-Käufe gleichzeitig | +75 % | **35 %** (Corona-Crash März 2020) |
| ohne 24-h-Sperre | +79 % | 24 % |

**Warum trotzdem die Sperre:** Im Datensatz stecken nur Coins, die überlebt haben. Ein Coin, der wie LUNA im Mai 2022 in
4 Tagen auf null fällt, signalisiert immer wieder „Einbruch“. Ohne Sperre würde die Regel ihn in der Simulation **52-mal**
nachkaufen (Totalverlust), mit 24 h Sperre nach einem Notstop **4-mal** (ca. −13 %). Die Sperre kostet im Rückblick rund
5 Prozentpunkte im Jahr. Das ist der Preis der Versicherung.

**Warum kein Tageslimit:** Ein Kaufstopp nach −6 % am Tag machte es schlechter, nicht sicherer: +65 % statt +75 % im Jahr
und ein größerer Rückgang (32 % statt 26 %), weil er genau die Crash-Käufe blockiert, die danach zurückfedern. Ersatz:
Notstopp für alles bei −40 % vom Höchststand.

**Startzeitpunkt:** Wer 2019 begann, lag bei +75 % im Jahr, 2022 bei +43 %, 2024 bei +38 %, **2025 bei +3,5 %** (bis 10/2026).
Der größte Rückgang blieb jeweils bei 25–26 %.

## 5. Abgleich: echter Bot gegen Simulation (`replay.py`)

Echte 15-Minuten-Kurse wurden durch den unveränderten Bot-Code gespielt (Takt 10 Sekunden, simulierte Börse mit Gebühren und
Mindestgrößen) und Trade für Trade mit der Simulation verglichen:

| Zeitraum | Trend: Bot / Simulation | Crash-Kauf: Bot / Simulation |
|---|---|---|
| 07–09/2024 (Crash 5. August) | 16 / 16 Trades, z. B. ZEC +48,8 % / +48,8 %, XRP +32,9 % / +32,8 % | 7 / 7 Trades, z. B. BNB −4,5 % / −4,6 % |
| 05–06/2021 (Crash 19. Mai) | 7 / 7 Trades, z. B. ETH +40,3 % / +40,2 % | 67 / 68 Trades, Ø +1,25 % / +1,67 % |

Der Abgleich hat zwei Fehler gefunden, die jetzt behoben sind: einen im Replay-Aufbau (Zeitstempel) und einen in der ersten
Kombi-Simulation (Zeit-Stop der Trend-Regel 5 statt 20 Tage). Die Zahlen oben sind die korrigierten.

## Was die Zahlen NICHT sagen

1. **Überlebende:** Alle 10 Coins gibt es 2026 noch, und sie gehören zu den größten. Gestorbene Coins (LUNA, FTT …) fehlen.
   Das schönt Trendfolge und Crash-Kauf. Gegenmittel im Bot: Crash-Kauf nur in diesen 10 großen Coins, Notstop, Sperre.
2. **Auswahl:** Die Trend-Regel wurde im alten Projekt auf Daten bis 2026 ausgesucht. Für sie ist 2023–2026 also nicht
   wirklich „ungesehen“. Die Crash-Regel ist neu und wurde nur auf 2017–2022 eingestellt.
3. **Ausführung:** Im Crash sind Spreads und Schlupf größer. Deshalb alle Hauptzahlen mit 0,30 % je Seite (doppelt so viel
   wie normal). Der Bot handelt USDC-Paare, die etwas weniger liquide sind als die getesteten USDT-Paare.
4. **Zeitgeist:** Die riesigen Jahre (2020, 2021, 2024) waren Bullenmärkte. 2025/2026 war es eine Seitwärts- bis Abwärtsphase,
   und die Kombination lag bei etwa ±0. Wer mit diesen Zahlen rechnet, sollte deutlich weniger erwarten und Rückgänge von
   30–40 % aushalten können.

## Nachrechnen

```bash
python3 -m venv .venv-forschung && .venv-forschung/bin/pip install numpy pandas pyarrow
bash research/download.sh /tmp/kurse                    # ca. 100 MB, prüft jede Datei
cd /tmp && /pfad/zu/NewTry/.venv-forschung/bin/python -I /pfad/zu/NewTry/research/load.py /tmp/kurse/raw /tmp/kurse/cache
python -I research/verify.py /tmp/kurse/cache           # Echtheit
python -I research/daytrade.py /tmp/kurse/cache         # 1. Daytrading
python -I research/dip_stress.py /tmp/kurse/cache research   # 2. Einbruch-Härtetest
python -I research/trend.py /tmp/kurse/cache            # 3. Trend und Momentum
python -I research/robust.py /tmp/kurse/cache research  # 4. Kombination und Stabilität
python -I research/final.py /tmp/kurse/cache research   # 4. Endgültige Einstellung, LUNA-Szenario
python -I research/replay.py /tmp/kurse/cache research . 2024-07-01 2024-10-01   # 5. Bot gegen Simulation
```

`python -I` und ein Arbeitsordner außerhalb der Daten sind Absicht: Heruntergeladene Dateien werden nie als Code ausgeführt.
