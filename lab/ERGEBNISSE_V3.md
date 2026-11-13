# Ergebnisse v3: Hebel und Copy-Trading

Stand 12.11.2026. Gleiche Daten und Regeln wie in [ERGEBNISSE_V2.md](ERGEBNISSE_V2.md) (10 Coins, Binance-Kurse bis
30.10.2026). Zwei Fragen aus dem Betrieb: Bringt Hebel mehr? Und kann man aus den Copy-Trading-Ranglisten von Binance
die besten Trader – oder ihre Muster – herausfiltern?

## 1. Hebel auf die Kombi (`lab/leverage.py`)

Bei Hebel L werden Risiko je Trend-Trade (1 % × L), Höchstanteil je Position (33 % × L) und Crash-Kauf-Größe (20 % × L)
vervielfacht; gekauft werden darf bis zum L-fachen des Kapitals. Geliehenes USDC kostet Zinsen (8 % bzw. 15 % im Jahr);
Zwangsliquidation wie bei Binance Cross-Margin (Vermögen/Schulden ≤ 1,1, bewertet zum Tiefstkurs jeder 15m-Kerze,
vor Stops und Zielen geprüft), Liquidationsgebühr 1 %. Sonst wie im Maßstab: Kosten 0,20 % je Seite, Kauf eine Minute
nach dem Signal. Hebel 1 ergibt exakt die bekannte Kombi (Abweichung 0).

| Hebel | 2020–10/2026 | größter Rückgang | 2022 | seit 2025 | Liquidationen |
|---|---|---|---|---|---|
| **1,0× (Bot heute)** | +80,2 % im Jahr | 27 % | +15 % | +7,9 % im Jahr | 0 |
| 1,5× | +128,4 % im Jahr | 37 % | +21 % | +8,2 % im Jahr | 0 |
| 2,0× | +179,0 % im Jahr | 47 % | +25 % | +6,1 % im Jahr | 0 |
| 3,0× | +278,4 % im Jahr | 63 % | +28 % | −3,9 % im Jahr | 0 |
| 5,0× | +285,7 % im Jahr | 97 % | +18 % | −36,9 % im Jahr | 1 |

Zins 8 % im Jahr; mit 15 % fast gleich (z. B. 2,0× seit 2025: +5,1 % statt +6,1 %). Die einzige Zwangsliquidation (5×)
war am 19.05.2021: Das Kapital fiel an einem Tag um 94,5 % vom Höchststand. Kelly-Hebel aus den Tagesrenditen der Kombi:
2020–2026 voll 6,4×, halb 3,2×; seit 2025 voll 1,6×, halb 0,8× – mit Kreditzins 8 % nur noch 0,44×, und der
Standardfehler ist so groß, dass das Band von −3,9× bis 7,0× reicht. Kelly sagt hier nichts Verlässliches.

**Mit dem Notstopp des Bots gerechnet** (−30 % vom Höchststand → alles verkaufen, Pause, danach gilt das Kapital als neuer
Höchststand; frischer Start 01/2025; nachgerechnet vom Prüfagenten und hier reproduziert):

| Hebel | Pause 24 h: Ertrag seit 2025 | größter Rückgang | Notstopps | Pause 7 Tage: Ertrag seit 2025 |
|---|---|---|---|---|
| 1,0× | +7,9 % im Jahr | 26 % | 0 | +7,9 % im Jahr |
| 1,5× | +6,2 % | 40 % | 2 | +5,2 % |
| 2,0× | +7,1 % | 44 % | 3 | +1,4 % |
| 3,0× | +23,7 % | 52 % | 6 | +10,6 % |

Folgerung: Hebel vervielfacht vor allem die Bullenjahre 2020, 2021 und 2024. Seit 2025 hängt das Ergebnis an Annahmen:
Ohne Notstopp schadet Hebel ab 2×, mit Notstopp sieht 3× gut aus – aber mit 6 Notstopps in 22 Monaten und mehr als der
Hälfte Rückgang, und eine Woche statt einen Tag Pause halbiert den Vorteil (2× fällt auf +1,4 %). Das ist kein
verlässlicher Vorteil, sondern ein großer Einsatz auf eine Annahme. Nicht enthalten (macht Hebel schlechter): Höchsthebel
und Leihgrenzen bei Binance, steigende USDC-Zinsen gerade in Crashs, in denen die Crash-Käufe leihen. Nicht enthalten
(macht Hebel besser): Stops, die vor der Liquidation greifen (dann gab es 2020–26 keine Liquidation). Der Bot bleibt
ohne Hebel.

## 2. Copy-Trading-Ranglisten: Können oder Glück? (`lab/copy_luck.py`)

Binance „Spot Copy → High ROI“ zeigt z. B. „+33,95 % in 30 Tagen bei 7,56 % Rückgang“. Versuch: 2.000 Händler **ohne
jedes Können** auf echten Kursen, 01/2020–10/2026. Sie kaufen zufällige Coins zu zufälligen Zeitpunkten und halten
zufällig lange, jeder mit eigenem Stil (1–5 Positionen, Haltedauer im Mittel 4 Stunden bis 10 Tage, teils mit
Gewinnziel und Stop). Kosten 0,10 % je Seite, keine Verzögerung, kein Schlupf. In jedem 30-Tage-Fenster eine Rangliste
wie in der App, dann der Blick auf den Folgemonat.

| | 2020–10/2026 (83 Monate) | seit 2025 (22 Monate) |
|---|---|---|
| Bester Zufallshändler je Monat (Median) | +53 % | +44 % |
| Monate mit mindestens einem Zufallshändler ≥ +30 % bei ≤ 7,6 % Rückgang | 54 % | 55 % |
| Monate mit mindestens einem Zufallshändler ≥ +18,8 % bei ≤ 5,3 % Rückgang | 59 % | 64 % |
| Folgemonat: Top-10 (Rückgang ≤ 10 %) | +0,8 % | −0,9 % |
| Folgemonat: alle Zufallshändler | −1,1 % | −3,6 % |
| Jeden Monat den Spitzenreiter des Vormonats kopieren (10 % Gewinnbeteiligung) | −16,5 % im Jahr | −43,3 % im Jahr |
| Zum Vergleich: die Kombi des Bots | +80,2 % im Jahr | +7,9 % im Jahr |

Mit 300 statt 2.000 Händlern gab es einen solchen „+30 % bei ≤ 7,6 %“-Monat in 28 % der Monate, mit 5.000 in 75 %. Echte
Trader handeln Hunderte Coins, auch sehr kleine – dort fallen die Glückstreffer noch größer aus als bei diesen 10 Coins.

Die Rangfolge trägt etwas Information (Rangkorrelation Monat → Folgemonat ≈ +0,15): Wer wenig handelt und voll
investiert ist, landet öfter oben und zahlt weniger Gebühren. Das ist Stil, kein Vorhersagekönnen – die Spitzenreiter
fallen im Folgemonat auf den Durchschnitt zurück.

**Wie lange müsste ein Trader handeln, damit Können nachweisbar ist?** Für eine Sharpe-Ratio S über T Jahre gilt
t ≈ S·√T. Ein Rekord von 67 Tagen braucht für t ≥ 2 eine Sharpe-Ratio von 4,7; unter 2.000 Tradern (Mehrfachtest,
einseitig 5 %/2.000 → t ≥ 4,06) sogar 9,5. Zum Vergleich: die Kombi kommt 2020–2026 auf t = 5,4 über 6,8 Jahre, also
eine Sharpe-Ratio von etwa 2.

**Was „Reverse Engineering“ leisten kann:** Mit der Trade-Liste eines einzelnen Traders (mindestens 50 abgeschlossene
Trades) lässt sich prüfen, ob seine Einstiege besser sind als zufällige Einstiege mit gleichen Coins und Haltedauern
(Zufallsvergleich wie in `stats.random_entry_test`). Nur wenn das hält, lohnt es, sein Muster als Regel zu fassen und
auf 2018–2026 zu testen. Die Ranglisten selbst liefern dafür keine Grundlage; Binance bietet für fremde
Lead-Portfolios keine offizielle Schnittstelle.

```bash
python -I lab/leverage.py /tmp/kurse/cache /tmp/kurse/cache1m
python -I lab/copy_luck.py /tmp/kurse/cache 2000        # 300 / 5000 für die Empfindlichkeit
```
