# Der gemeinsame Maßstab (vor der Auswertung festgelegt)

Stand 08.11.2026. Diese Regeln wurden **geschrieben, bevor** die neue Forschungsrunde Ergebnisse geliefert hat. Ein
Kandidat gewinnt nicht, weil er im Rückblick gut aussieht, sondern weil er unter diesen Bedingungen den größten
**nachweisbaren** Netto-Vorteil bei tragbarem Risiko hat. Danach wird nichts mehr an den Regeln gedreht.

## 1. Identische Bedingungen für alle Kandidaten

| | |
|---|---|
| Daten | Binance-Kerzen (Speirsy11/crypto-dataset, SHA-256 geprüft), 10 Coins, 1m/15m |
| Zeitraum | **ab 01.01.2018**. 2017 ist ausgeschlossen: Binance war wenige Wochen alt, Fehlprints wie ETH 144 statt 300 USDT (22.08.2017) sind nicht handelbar |
| Zeitachse | eine 15-Minuten-Achse für alle; Bewertung des Kapitals in jeder Kerze (Rückgang auch innerhalb des Tages) |
| Ausführung | Entscheidung auf dem Kerzenschluss, Kauf/Verkauf **zum Kurs der 2. Minute danach** (1m-Daten), nie zum Schlusskurs |
| Kosten | **0,20 % je Seite** (0,10 % Gebühr + 0,10 % Spread/Schlupf); Härtetest **0,40 %** |
| Kapital | Spot, kein Hebel, keine Leerverkäufe, gekauft wird nur mit freiem Geld |
| Stop/Ziel | Stop vor Ziel in derselben Kerze; Kurslücken zum Eröffnungskurs |

## 2. Prüfverfahren: Walk-Forward statt Rückblick

Für jede Familie wird ihr Parameter-Raster gerechnet. Für jedes Prüfjahr 2020 … 2026 wird **nur mit Daten vor diesem
Jahr** die beste Einstellung gewählt (Ziel: Wachstum, Abzug für Rückgänge über 30 %) und dann auf dem Prüfjahr gehandelt.
Die aneinandergereihten Prüfjahre sind die **ehrliche Schätzung** einer Familie, inklusive der Kosten der
Parameter-Auswahl. Vorab festgelegte Einstellungen (NewTry, Gemini) laufen zusätzlich unverändert mit.

## 3. Die Kennzahl, nach der entschieden wird

**Gesicherter Netto-Ertrag** = 10-%-Quantil des jährlichen Netto-Wachstums im Walk-Forward-Zeitraum 2020–10/2026
(Block-Bootstrap der Tagesrenditen, Blocklänge 20 Tage, 2.000 Ziehungen). In Worten: Mit 90 % Sicherheit war das Wachstum
mindestens so hoch. Angegeben als Rendite pro Jahr nach allen Kosten.

**Risikogrenzen** (Ausschluss, wenn verletzt):
* größter Rückgang im Bootstrap, 90-%-Quantil, **höchstens 45 %**
* Härtetest mit 0,40 % Kosten je Seite: Wachstum **positiv**

**Belege** (werden immer ausgewiesen, entscheiden über „Vorteil belegt“ oder „nur Marktrisiko“):
* **Deflated Sharpe Ratio** ≥ 0,95 über die Zahl aller getesteten Varianten (Mehrfachtest-Korrektur)
* **Alpha** gegenüber „alle Coins gleich gewichtet halten“ mit Newey-West-t ≥ 2: Verdienst über das reine Marktrisiko hinaus
* **Zufallsvergleich** (aus azubiassist) für Einstiegsregeln: p ≤ 0,05 gegen zufällige Einstiege mit gleichen Ausstiegen

**Robustheit** (wird ausgewiesen): Parameter-Nachbarn, jedes Jahr einzeln, Coins einzeln weggelassen, ohne bestes Jahr.

## 4. Portfolio

Kandidaten, die die Risikogrenzen bestehen, werden als getrennte Töpfe kombiniert. Die Gewichte werden ebenfalls per
Walk-Forward gewählt (nur Daten vor dem Prüfjahr, Schritte von 10 %). Das Portfolio wird mit derselben Kennzahl bewertet
und muss den besten Einzelkandidaten beim gesicherten Netto-Ertrag schlagen, sonst gewinnt der Einzelkandidat.

## 5. Was dieser Maßstab nicht kann

* **Überlebende:** Der Datensatz enthält nur Coins, die 2026 noch groß sind. Kauf-Strategien auf Altcoins sind dadurch
  geschönt. Strategien, die nur BTC/ETH handeln, sind davon kaum betroffen. Das wird bei der Auswahl offen gewichtet.
* **Orderbuch:** Historische Spreads im Crash sind unbekannt. Die 1-Minuten-Verzögerung und der Härtetest fangen einen
  Teil ab, nicht alles.
* Ein Rückblick bleibt ein Rückblick. Die Zahlen sind Obergrenzen, keine Versprechen.

## Nachtrag Runde 2b (08.11.2026, vor der Auswertung festgelegt): Kandidaten aus der Gemini-Recherche

Die sechs Kandidaten aus dem Rechercheauftrag an Gemini laufen unter **denselben Bedingungen** wie oben (Abschnitte 1–3),
mit genau den Standardwerten und Prüfrastern, die Gemini angegeben hat. Dort, wo Gemini „eigene Ergänzung“ markiert hat
(Notstop, Positionsgröße, Mindestverlust), gilt die Ergänzung unverändert. Hinzu kommen:

* **Mehrfachtest:** Die neuen Varianten zählen zu den bisherigen 515 dazu; die Hürde steigt entsprechend.
* **Ergänzungs-Prüfung:** Jeder Kandidat (Walk-Forward) wird zusätzlich als fester Anteil neben die NewTry-Kombination
  gestellt: **80 % Kombi + 20 % Kandidat** (stündlich auf Zielgewicht). Ein Kandidat kommt nur dann für den Bot in Frage,
  wenn diese Mischung den gesicherten Netto-Ertrag der Kombi allein **übertrifft**, der Rückgang (90-%-Quantil) **nicht
  steigt** und der Härtetest des Kandidaten (0,40 % je Seite) positiv bleibt.
* Kandidat 5 (Drawdown-gesteuerte Volatilitäts-Allokation) wird wie beschrieben als Modul mit 40 % des Kapitals gerechnet
  (Rest Cash). Sein Hauptbeleg (arXiv:2511.13251) war nicht auffindbar; das Ergebnis wird entsprechend eingeordnet.
  *Korrektur nach der Auswertung: Die Arbeit existiert; sie untersucht chinesische Aktien, keine Kryptowährungen.*
