# Forschungsrunde v2: NewTry + azubiassist zusammengeführt, alle Kandidaten unter identischen Bedingungen

Stand: 08.11.2026. Grundlage: der vorab festgelegte Maßstab in [MASSSTAB.md](MASSSTAB.md). Alle Zahlen lassen sich mit
den Skripten in diesem Ordner nachrechnen (ganz unten).

## Kurz

> **Nachtrag Runde 2b:** Sechs weitere Kandidaten aus einer Literatur-Recherche (Gemini) wurden unter demselben
> Maßstab geprüft; keiner verbessert den Bot ([ERGEBNISSE_V2B.md](ERGEBNISSE_V2B.md)).

* **Gewinner nach dem Maßstab: die bestehende NewTry-Kombination** (Trend-Ausbruch 4h + Crash-Kauf in einem gemeinsamen
  Depot). Realistisch gerechnet 2020–10/2026: **+80 % pro Jahr, größter Rückgang 26–28 %, gesicherter Netto-Ertrag +51 %**
  (10-%-Quantil). Sie ist der einzige Kandidat, der auch nach Korrektur für 515 getestete Varianten belegt ist
  (Sharpe-t 5,4 und Alpha-t 4,3 über der Bonferroni-Hürde 3,73).
* **Keine neue Familie schlägt sie.** Zeitreihen-Momentum, Querschnitts-Momentum und ein BTC/ETH-Kerntrend verdienen vor
  allem Marktrisiko (Alpha nicht belegt) und fallen 44–56 % tief. Ein per Walk-Forward optimiertes Portfolio aus allen
  Familien war schlechter (+41 %/Jahr, gesichert +17 %) als die einfache Kombination.
* **Die Gemini-Vorschläge verlieren deutlich.** „Trend-Pullback mit Teilverkauf“ (−40 %/Jahr) und „gestaffelter Dip in
  3 Tranchen“ (−11 %/Jahr): zu viele Trades für einen Brutto-Vorteil nahe null bzw. Nachkaufen, das Verluste auf voller
  Größe realisiert. In keiner der 70 Varianten beider Familien positiv.
* **Die dokumentierten +77 % waren zu optimistisch.** Realistisch (ohne 2017, Kauf 1 Minute nach Kerzenschluss, Rückgang
  in jeder Kerze, Kosten 0,30 %): +60 % pro Jahr, Rückgang 28 %. **Seit 2025 nur noch +8 % pro Jahr.**
* **Der Crash-Kauf ist der empfindliche Teil:** echter Vorteil je Einstieg (Zufallsvergleich p = 0,003), aber 1 Minute
  Verzögerung kostet ein Drittel davon, und 2025/26 lag er bei ≈ 0. Deshalb bekommt er im Bot einen Ausführungswächter.

## 1. Bestandsaufnahme

| | **NewTry** (operative Basis) | **azubiassist** (Forschungs- und Sicherheitsfundament) |
|---|---|---|
| Umfang | ≈ 5.700 Zeilen, 86 Tests (alle grün) | ≈ 41.000 Zeilen, 358 Tests (alle grün, 12 Min.) |
| Handel | Binance Spot, 2 feste Regeln, gemeinsames Depot | Binance + Coinbase, Kurzfrist-Strategien, Swing-Regeln, KI-Rat |
| Sicherheit | Stop-Order an der Börse (Notbremse), Abgleich, Absturzschutz je Order, Notstopp −40 %, Wächter | unveränderliche Risikogrenzen, Buchprüfer, Ausführungsjournal, Schlüssel-Hygiene, Abbruchregeln, Kapital-Rampe, Testnet-Generalprobe |
| Forschung | Skripte je Frage, 2017–2026 auf 10 Coins | Regelsprache, Zufallsvergleich, Bonferroni, Tresor, Vorab-Registrierung, Stärke-Test, Vorwärtstest |
| Problem | Zahlen nicht unter realistischen Ausführungsbedingungen geprüft | handelte nie (Kapital-Rampe 5 % → Orders unter dem Binance-Minimum) |

Übernommen aus azubiassist: **Zufallsvergleich** (`stats.random_entry_test`), **Mehrfachtest-Korrektur**, **vorab
festgelegter Maßstab** (statt Tresor), **Vorwärtstest** und **Schlüssel-Hygiene** (im Bot, `guards.py`), die Idee des
**Live-Schattens** als Ausführungswächter. Bewusst nicht übernommen: KI im Handelsweg, Richter/Allokator, Kapital-Rampe,
Verfassung, Dashboard, Update-Agent. Jede dieser Instanzen kann einen Kauf verhindern, keine verbessert den Erwartungswert.

## 2. Maßstab

Siehe [MASSSTAB.md](MASSSTAB.md): ab 2018, 15m-Zeitachse, Kauf/Verkauf zum Kurs der 2. Minute nach dem Signal (1m-Daten),
0,20 % Kosten je Seite (Härtetest 0,40 %), Walk-Forward je Prüfjahr 2020–2026. Entscheidend ist der **gesicherte
Netto-Ertrag** (10-%-Quantil im Block-Bootstrap) bei einem 90-%-Rückgang von höchstens 45 % und positivem Härtetest.

## 3. Prüfung der vorhandenen Backtests

**Reproduziert:** Alle NewTry-Zahlen (`trend.py`, `robust.py`, `final.py`) stimmen auf die Nachkommastelle. Die neue
Maschine (`engine.sim_joint`) bildet `research/combo.py` exakt nach (+77,6 % statt +77,4 %, 909 Crash-Trades wie dort).

**Gefundene Verzerrungen** (Überleitung mit `waterfall.py`, jeweils eine Annahme geändert):

| Schritt | pro Jahr | Rückgang |
|---|---|---|
| Dokumentiert (NewTry ERGEBNISSE.md) | +77,4 % | 25 % |
| nachgerechnet mit denselben Annahmen | +77,4 % | 25 % |
| ohne 2017 | +69,3 % | 25 % |
| Kauf 1 Minute nach Kerzenschluss | +59,7 % | 26 % |
| Rückgang in jeder 15m-Kerze statt einmal am Tag | +59,7 % | 28 % |
| Kosten 0,20 % statt 0,30 % (Maßstab) | +70,9 % | 27 % |
| nur 2020–10/2026 | +80,2 % | 27 % |
| nur 2025–10/2026 | **+7,9 %** | 26 % |

1. **Fehlprints 2017.** Der beste Crash-Trade (+107 % in 4 Stunden, ETH 22.08.2017) kaufte zu 144,21 USDT, einem einzelnen
   Print in einer Minute mit 16 ETH Umsatz bei einem Kurs um 300. Allein dieser Trade machte rund +21 % Kapital aus.
2. **Kauf zur Eröffnung.** Die Simulation kaufte zum ersten Kurs der Folgekerze, also in der Sekunde des Kerzenschlusses.
   Nach Crashs federt der Kurs oft genau in dieser ersten Minute zurück: 1 Minute später sinkt der Ø-Crash-Trade von
   +1,12 % auf +0,76 %, zum Hoch der ersten Minute auf +0,30 % (`dip_exec_check.py`, 973 Trades, Kosten 0,30 %).
3. **Rückgang einmal am Tag gemessen.** Crash-Positionen fallen innerhalb des Tages tiefer: Crash-Kauf allein 22 % statt 15 %.
4. **Geprüfter Zeitraum nicht ungesehen.** Die Trend-Regel wurde in azubiassist auf Daten bis 2026 gewählt; die
   Crash-Schwelle −9 % nach einem Blick auf 2023–2026. Der Walk-Forward zeigt, dass beides den Befund nicht trägt:
   Die ehrlich gewählte Trend-Familie war sogar besser (+64 %), und −10 % liefert dasselbe wie −9 % (gesichert +51 %).
5. **Skript und Doku widersprechen sich.** `final.py` rechnet mit 5 Crash-Käufen (Rückgang 35 %), Doku und Bot mit 3.
6. **Überlebende** (nicht messbar mit diesem Datensatz): alle 10 Coins existieren 2026 noch. Dagegen helfen nur die
   Gegenmittel im Bot (Crash-Kauf nur in großen Coins, Notstop, 24-h-Sperre) und vorsichtige Erwartungen.
7. **Der Bot handelt Trend auf 25 Coins, geprüft sind 10.** Jeden der 10 Coins einzeln wegzulassen ändert wenig
   (+43 bis +58 %/Jahr), azubiassist fand auf 5 weiteren Coins einen positiven Vorteil. Belegt ist es für die 15 neuen nicht.

azubiassist: Seine Echtdaten-Studien (Teil 18/20) kommen zum selben Kern: Auf 1m–15m hält nach Gebühren nichts, auf 4h
trägt der Ausbruch. Dessen Zufallsvergleich bestätigt sich hier: echte Einstiege +2,85 % je Trade gegen +1,03 % bei
zufälligen Einstiegen mit denselben Ausstiegen (p = 0,003, t = 5,2).

## 4. Kandidaten (515 Varianten in 7 Familien + 6 feste Einstellungen + 4 Vergleichsgrößen)

| Familie | Herkunft | Raster |
|---|---|---|
| TREND4H | NewTry | Ausbruch 50/100/200 · Stop 1,5/2/3 ATR · Ziel 8/15/kein · 10/20/40 Tage (81) |
| CRASH | NewTry | Einbruch 6–15 % · in 1/4/12 h · halten 1–24 h · Notstop 10/15/20 % (270) |
| TSMOM | neu | Zeitreihen-Momentum je Coin, 5 Rückblick-Sätze, Gewicht nach Schwankung, täglich/wöchentlich (30) |
| XSMOM | neu | die 2/3/5 stärksten Coins über 14–90 Tage, optional nur bei BTC über SMA 100, Schwankungs-Deckel (48) |
| CORE | neu | BTC bzw. BTC+ETH über SMA 50–200, optional Schwankungs-Deckel; kaum Überlebenden-Verzerrung (16) |
| PULLBACK | Gemini A | Rücksetzer im Aufwärtstrend: 1h-RSI, Bollinger-Mitte, grüne Umkehrkerze, 50 % Teilverkauf, ATR-Trailing (54) |
| TRANCHE | Gemini B | 3 Tranchen 30/35/35 % bei −2,5/−5/−8 %, Ziel +1,6–2,2 % auf den Durchschnitt, EMA-20-Ausstieg, Stop −11 % (16) |

## 5. Vergleich unter identischen Bedingungen (2020–10/2026)

Walk-Forward = Einstellung je Prüfjahr nur aus den Jahren davor gewählt. Fest = Einstellung vorab bekannt. Rückgänge in
dieser Tabelle auf Stundenbasis (für alle gleich); in jeder 15m-Kerze gemessen liegen sie 1–2 Punkte höher (Kombi 27–28 %).

| Kandidat | pro Jahr | Rückgang | **gesichert** | Rückgang 90 % | Härtetest | Alpha (t) | Sharpe |
|---|---|---|---|---|---|---|---|
| **NewTry-Kombi (fest)** | **+80 %** | 26 % | **+51 %** | 38 % | +56 % | +42 % (4,3) | 2,06 |
| Kombi, Crash ab −10 % | +81 % | 26 % | +51 % | 38 % | +60 % | +44 % (4,4) | 2,13 |
| Kombi, Crash nur 10 % je Kauf | +68 % | 24 % | +42 % | 36 % | +51 % | +35 % (3,9) | 1,97 |
| TREND4H (Walk-Forward) | +64 % | 33 % | +33 % | 48 % ✗ | +52 % | +31 % (2,5) | 1,55 |
| NewTry-Trend allein (fest) | +55 % | 25 % | +32 % | 38 % | +45 % | +28 % (3,1) | 1,73 |
| alle Coins gleich gewichtet halten | +85 % | 74 % | +31 % | 83 % ✗ | – | – | 1,28 |
| XSMOM (Walk-Forward) | +50 % | 56 % | +17 % | 69 % ✗ | +48 % | +15 % (1,1) | 1,14 |
| Portfolio aller Familien (Walk-Forward) | +41 % | 43 % | +17 % | 51 % ✗ | – | +20 % (1,9) | 1,29 |
| TSMOM (Walk-Forward) | +38 % | 44 % | +16 % | 55 % ✗ | +39 % | +8 % (1,1) | 1,24 |
| halb Coins, halb Cash | +35 % | 38 % | +15 % | 49 % ✗ | – | +1 % (0,3) | 1,23 |
| CORE BTC/ETH (Walk-Forward) | +41 % | 50 % | +14 % | 61 % ✗ | +38 % | +10 % (0,9) | 1,09 |
| NewTry-Crash allein (fest) | +16 % | 17 % | +9 % | 24 % | +7 % | +15 % (2,8) | 1,06 |
| CRASH (Walk-Forward) | +12 % | 28 % | +5 % | 32 % | +1 % | +9 % (1,7) | 0,82 |
| BTC halten | +42 % | 77 % | +5 % | 86 % ✗ | – | – | 0,89 |
| PULLBACK (Gemini A, Walk-Forward) | −9 % | 59 % | −14 % | 68 % ✗ | −22 % | −16 % (−3,5) | −0,65 |
| TRANCHE (Gemini B, Walk-Forward) | −11 % | 60 % | −18 % | 78 % ✗ | −23 % | −19 % (−2,9) | −0,63 |
| Gemini-Hybrid (fest, wie vorgeschlagen) | −26 % | 88 % | −31 % | 92 % ✗ | −49 % | −40 % (−8,6) | −2,02 |

Kombi pro Jahr (2018–2026): 2018 +24 % · 2019 +65 % · 2020 +205 % · 2021 +223 % · 2022 +15 % · 2023 +82 % ·
2024 +137 % · 2025 +15 % · 2026 (bis Okt.) +0 %. 35 % der Monate im Minus, schlechtester −15 %, längste Phase ohne neuen
Höchststand 262 Tage.

## 6. Robustheit

| Prüfung | Trend (NewTry) | Crash-Kauf (NewTry) |
|---|---|---|
| Zufallsvergleich 2020–26 (gleiche Ausstiege, 300 Läufe) | +2,85 % gegen +1,03 % je Trade, p = 0,003, t = 5,2 | +1,20 % gegen −0,37 %, p = 0,003, t = 4,9 |
| jeder Coin einzeln weggelassen | +43 % bis +58 %/Jahr | +12 % bis +21 %/Jahr |
| ohne bestes Jahr | +42 %/Jahr | +12 %/Jahr |
| Kauf zur Eröffnung statt 1 Minute später | +61 % statt +55 % | +22 % statt +16 % |
| Parameter-Nachbarn (Walk-Forward-Raster) | 81 von 81 Varianten positiv, Median +39 % | 74 % positiv, Median +8 % |
| Härtetest 0,40 % je Seite | +45 % | +7 % |

**Mehrfachtest:** 515 Varianten. Bonferroni-Hürde (einseitig 5 %): t ≥ 3,73. Die Kombi besteht sie (Sharpe-t 5,4,
Alpha-t 4,3), Trend allein knapp nicht (Alpha-t 3,1), Crash allein nicht (2,8). Deflated Sharpe Ratio mit theoretischer
Null (alle 515 ohne echten Vorteil): Kombi 0,99, Trend 0,93, Crash 0,39. Mit der empirischen Streuung innerhalb der Familien
(die strengste Lesart, aufgebläht durch die sehr unterschiedlichen Crash- und Pullback-Varianten) besteht kein Kandidat
(Kombi 0,05). Ehrliche Lesart: Der Einstiegsvorteil beider Regeln ist klar belegt; als Depot ist erst die Kombination
nach Mehrfachtest belastbar.

## 7. Auswahl

**NewTry-Kombination, unverändert:** Trend 1 % Risiko, max. 3 · Crash-Kauf ab −9 % in 4 h, 20 %, max. 3, Notstop −15 %,
nach 4 h raus, 24 h Sperre. Gründe: höchster gesicherter Netto-Ertrag, alle Risikogrenzen eingehalten, als einziger Kandidat
nach Mehrfachtest belegt, und sie läuft schon (Trade-für-Trade gegen die Simulation abgeglichen, Ausfall-Test bestanden).
−9 % und −10 % sind gleichwertig; es gibt keinen Beleg, der einen Wechsel rechtfertigt.

Risikostufen (Einordnung, keine Empfehlung zum Hochdrehen; `live_reference.py`):

| Trend-Risiko / Crash-Größe | 2020–10/2026 | Rückgang | schlechtester Monat | seit 2025 |
|---|---|---|---|---|
| 0,75 % / 15 % | +60 %/Jahr | 20 % | −11 % | +8 %/Jahr |
| 1,0 % / 10 % | +68 %/Jahr | 25 % | −10 % | +9 %/Jahr |
| **1,0 % / 20 % (Standard)** | **+80 %/Jahr** | **27 %** | **−15 %** | **+8 %/Jahr** |
| 1,5 % / 20 % | +101 %/Jahr | 34 % | −17 % | +3 %/Jahr |

**Erwartung mit 150 €:** In einem Markt wie 2025/26 eher 0 bis +15 % im Jahr (ein paar bis 20 €). Die hohen Durchschnitte
kommen aus 2020, 2021 und 2024. Zwischendurch 25–35 % unter dem Höchststand sind normal (150 € → etwa 100–110 €).

## 8. Was daraus im Bot folgt (`guards.py`)

Die Regeln bleiben. Neu sind drei Wächter, die prüfen, ob die Wirklichkeit noch zur Simulation passt:

1. **Ausführungswächter (Crash-Kauf):** Jeder Kauf wird mit dem Schluss der Signal-Kerze verglichen (Simulation: Crash
   +0,15 %, Trend +0,07 % im Mittel). Liegen die letzten 10 Crash-Käufe im Schnitt mehr als 0,35 Prozentpunkte darüber,
   wird nur der Crash-Kauf ausgesetzt (`/weiter` schaltet ihn wieder ein). Gewinnschwelle über 2018–2026: ≈ 0,67 % Kosten
   je Seite; 2025/26 deutlich weniger.
2. **Vorwärtstest:** Ø der letzten 30 Trades je Regel gegen das 5-%-Quantil von 30 aufeinanderfolgenden Trades im
   Rückblick (Trend −1,69 %, Crash −0,89 %). Nur Meldung, kein Eingriff.
3. **Schlüssel-Hygiene:** täglich im Echtgeld-Betrieb: Darf der Schlüssel auszahlen? Darf er noch handeln?

## 9. Was die Zahlen nicht sagen

* Überlebende: Nur Coins, die 2026 noch groß sind. Für alle Kauf-Strategien auf Altcoins ein Bestfall.
* Orderbuch: Spreads im Crash sind historisch unbekannt; die 1-Minuten-Verzögerung und der Härtetest decken einen Teil ab.
* USDC statt USDT: Der Bot handelt USDC-Paare, getestet sind USDT-Paare (liquider).
* Regime: 2020, 2021 und 2024 waren Bullenmärkte. Seit 2025 lag die Kombi bei ≈ +8 % im Jahr.

## Nachrechnen

```bash
python3 -m venv .venv-lab && .venv-lab/bin/pip install -r lab/requirements.txt
bash research/download.sh /tmp/kurse                                   # 10 Coins, 15m/1h/1d, SHA-256-geprüft
# 1m-Daten (≈ 800 MB): in research/download.sh "for i in 1h 15m 1d" durch "for i in 1m" ersetzen, dann
#   python -I lab/load_1m.py /tmp/kurse/raw /tmp/kurse/cache1m
cd /tmp && /pfad/NewTry/.venv-lab/bin/python -I /pfad/NewTry/research/load.py /tmp/kurse/raw /tmp/kurse/cache
python -I /pfad/NewTry/lab/research.py /tmp/kurse/cache /tmp/kurse/cache1m /tmp/lab-out     # Abschnitt 5 (≈ 3 Min.)
python -I /pfad/NewTry/lab/portfolio.py /tmp/kurse/cache /tmp/kurse/cache1m /tmp/lab-out TREND4H CRASH TSMOM XSMOM CORE
python -I /pfad/NewTry/lab/robust.py /tmp/kurse/cache /tmp/kurse/cache1m /tmp/lab-out \
  'NEWTRY_TREND:TREND4H={"n":100,"sl":2.0,"tp":15.0,"mb":120}' 'NEWTRY_CRASH:CRASH={"x":0.09,"lb":16,"h":16,"s":0.15}'
python -I /pfad/NewTry/lab/waterfall.py /tmp/kurse/cache /tmp/kurse/cache1m                  # Überleitung (Abschnitt 3)
python -I /pfad/NewTry/lab/live_reference.py /tmp/kurse/cache /tmp/kurse/cache1m             # Werte für guards.py
```

| Datei | Inhalt |
|---|---|
| `MASSSTAB.md` | der vorab festgelegte Erfolgsmaßstab |
| `data.py` | eine 15m-Achse für alle Coins, Ausführungspreis aus 1m-Daten, höhere Zeitebenen |
| `engine.py` | Simulation (numba): Einzel-Trades, Zielgewichte, Tranchen, gemeinsames Depot wie im Bot |
| `stats.py` | Kennzahlen, Block-Bootstrap, Deflated Sharpe, Alpha (Newey-West), Zufallsvergleich |
| `families.py` | alle Strategiefamilien mit Raster |
| `research.py` · `portfolio.py` · `robust.py` | Walk-Forward-Vergleich · Portfolio-Auswahl · Robustheit |
| `waterfall.py` · `live_reference.py` | Überleitung · Referenzwerte der Wächter |
| `load_1m.py` · `dip_exec_check.py` | 1m-Cache · Crash-Kauf minutengenau (Verzögerung, Fehlprint 2017) |
