# Runde 2b: Die Kandidaten aus der Gemini-Recherche unter dem gemeinsamen Maßstab

Stand: 08.11.2026. Grundlage: der Rechercheauftrag an Gemini (Bericht „Belegte Handelsstrategien für einen
Long-Only-Binance-Spot-Bot …“, 42 Seiten, 6 Kandidaten, Teile A–E) und die vorab festgelegten Regeln im
[Nachtrag zu MASSSTAB.md](MASSSTAB.md#nachtrag-runde-2b-08112026-vor-der-auswertung-festgelegt-kandidaten-aus-der-gemini-recherche).

## Kurz

* **Keiner der sechs Kandidaten verbessert den Bot.** Als 20-%-Beimischung neben der NewTry-Kombination senken fünf den
  gesicherten Netto-Ertrag deutlich (+38 % bis +43 % statt +51 %). Der sechste (Tages-Kanalausbruch) liefert einen
  Gleichstand (+51,0 % statt +51,2 %), keine Verbesserung.
* **Der Tages-Kanalausbruch sieht allein stark aus (+72 %/Jahr), hängt aber an wenigen Ausreißern.** Ein ZEC-Trade
  09/2025 brachte +790 %, ein BNB-Trade 12/2020 +827 %. Ohne ZEC fällt die feste Einstellung von +104 % auf +57 %/Jahr.
  Der Rückgang (90-%-Quantil) liegt bei 72 %. Das ist die Überlebenden-Verzerrung in Reinform.
* **Kalender-Effekte (Monatswechsel, Montag) und die Tages-Umkehr tragen nach Kosten auf diesen 10 Coins nicht.**
  Das deckt sich mit den Widerlegungen, die Gemini selbst zitiert.
* **Der einzige Vorschlag mit sicher positivem Erwartungswert ist Teil E** (Zinsen auf ungenutztes USDC): Die Kombi ist
  im Mittel nur zu **27 %** investiert und liegt **40 % der Zeit** fast ganz in USDC. Dazu unten mehr; umgesetzt ist das
  nicht.
* Die NewTry-Kombination bleibt auch nach jetzt 662 getesteten Varianten belegt (Sharpe-t 5,4, Alpha-t 4,3 über der
  Bonferroni-Hürde von 3,79).

## 1. Stichprobe der Quellen

| Quelle | Prüfung |
|---|---|
| Bianchi, Babiak, Dickerson 2022, *J. Banking & Finance* 142, 106547 (Kandidat 1) | existiert; Zeitraum laut Abstract 03/2017–03/2022 (Gemini: „bis Ende 2021“); Effekt vor allem in kleinen, wenig liquiden Paaren |
| Dobrynskaya 2023, *J. Alternative Investments* 26(1) (Kandidat 2) | existiert; Kernaussage stimmt |
| Kumar 2022, *Managerial Finance* 48(5); Vasileiou 2023, *IJBAAF* 13(3) (Kandidat 3) | existieren; Kumar nennt +21,77 %/+47,10 % p. a. gegenüber Halten (BTC/LTC), was Gemini als „nicht angegeben“ führte |
| Hudson & Urquhart 2021, *Annals of OR* 297 (Kandidat 4) | existiert; ≈ 15.000 Regeln mit Data-Snooping-Korrektur; die Out-of-Sample-Aussage konnte ich nicht prüfen |
| arXiv:2511.13251 (Hauptbeleg Kandidat 5) | existiert (Nguyen, 11/2025); die 6-%-Drawdown-Regel mit 1 Tag Pause steht dort wörtlich. **Untersucht werden aber chinesische Aktien 2023–2025, keine Kryptowährungen** (Geminis Karte sprach von Kryptowährungen). Korrektur: Meine erste Suche über die Nummer hatte sie nicht gefunden. |
| arXiv:2608.10375 „VolRouter“ (Kandidat 5) | existiert, behandelt aber Volatilitätssteuerung als Routing-Problem; Kandidat 5 ist eine Konstruktion von Gemini |
| Caporale & Plastun 2019 (Kandidat 6) | nicht einzeln geprüft (bekannte Studie); Gemini nennt selbst die Widerlegungen |

## 2. Ergebnisse unter identischen Bedingungen (2020–10/2026, 0,20 % je Seite, Kauf 1 Minute nach Signal)

Walk-Forward = Einstellung je Prüfjahr nur aus den Jahren davor gewählt; „Gemini fest“ = Geminis Standardwerte unverändert.

| Kandidat | Walk-Forward/Jahr | Rückgang | gesichert | Rückgang 90 % | Härtetest 0,40 % | Alpha (t) | Gemini fest |
|---|---|---|---|---|---|---|---|
| **NewTry-Kombi (zum Vergleich)** | **+80 %** | **26 %** | **+51 %** | **38 %** | **+56 %** | **+42 % (4,3)** | – |
| 4 Tages-Kanalausbruch (TRB) | +72 % | 49 % | +26 % | 72 % ✗ | +70 % | +33 % (2,0) | +70 % |
| 2 Verlierer-Umkehr (4–26 Wochen) | +21 % | 32 % | +3 % | 55 % ✗ | +4 % | +5 % (0,6) | +13 % |
| 3 Monatswechsel (BTC/ETH) | +12 % | 43 % | +3 % | 36 % | +10 % | +6 % (1,0) | +2 % |
| 5 Drawdown-gesteuerte Vol.-Allokation (40 %-Modul) | +7 % | 37 % | −2 % | 47 % ✗ | +2 % | −2 % (−0,3) | +10 % |
| 6 Montags-Effekt (BTC) | −1 % | 12 % | −3 % | 26 % | −4 % | −2 % (−1,1) | −1 % |
| 1 Tages-Umkehr bei niedrigem Volumen | −6 % | 46 % | −11 % | 59 % ✗ | −12 % | −10 % (−2,1) | −11 % |

**Ergänzungsprüfung** (vorab festgelegt: 80 % Kombi + 20 % Kandidat; Kombi allein: gesichert +51,2 %, Rückgang 90 % 38 %):

| Beimischung | gesichert | Rückgang 90 % | Korrelation zur Kombi | Ergebnis |
|---|---|---|---|---|
| Tages-Kanalausbruch | +51,0 % | 37 % | +0,39 | Gleichstand, nicht bestanden |
| Verlierer-Umkehr | +42,8 % | 36 % | +0,42 | nicht bestanden |
| Monatswechsel | +42,5 % | 33 % | +0,21 | nicht bestanden |
| Drawdown-gesteuerte Vol.-Allokation | +40,4 % | 35 % | +0,48 | nicht bestanden |
| Montags-Effekt | +40,2 % | 32 % | +0,14 | nicht bestanden |
| Tages-Umkehr bei niedrigem Volumen | +38,6 % | 33 % | +0,03 | nicht bestanden |

Die Beimischungen senken den Rückgang leicht, weil 20 % des Kapitals aus der Kombi abgezogen werden. Den Ertrag senken
sie stärker. Für eine Verbesserung müsste der Kandidat selbst mehr verdienen oder zu anderen Zeiten verdienen als die
Kombi; beides trifft nicht zu.

## 3. Einordnung je Kandidat

1. **Tages-Umkehr bei niedrigem Volumen:** 122 Trades pro Jahr, im Schnitt −0,42 % je Trade nach Kosten. Die Studie
   findet den Effekt vor allem bei kleinen, illiquiden Paaren; auf 10 großen Coins und nur mit Kauf bleibt nichts.
   Keine einzige der 27 Varianten ist positiv.
2. **Verlierer-Umkehr:** 96 % der Varianten positiv, aber kein Vorteil über das Marktrisiko (Alpha-t 0,6) und Jahre wie
   2022 (−21 %) und 2025 (−10 %), in denen sie gerade nicht hilft.
3. **Monatswechsel:** 2020/21 stark, 2024 (−21 %) und 2025 (−16 %) negativ – wie die von Gemini zitierte Replikation
   (kein Effekt mehr bei BTC 2019–2023) erwarten lässt.
4. **Tages-Kanalausbruch:** echte Trendfolge mit sehr wenigen Trades (≈ 10 pro Jahr) und daher kostenrobust (Härtetest
   +70 %). Aber: Rückgang 49 % (90 %: 72 %), Alpha-t 2,0 deutlich unter der Hürde, und der Ertrag kommt aus wenigen
   Ausreißern in Coins, von denen man heute weiß, dass sie überlebt und gestiegen sind (BNB 12/2020 +827 %, ZEC 09/2025
   +790 %, SOL 08/2021 +386 %). Ohne ZEC: +57 % statt +104 %/Jahr. Er verdient im Wesentlichen dasselbe wie die bereits
   laufende 4h-Trendregel, nur mit größeren Rückgängen.
5. **Drawdown-gesteuerte Volatilitäts-Allokation:** Der 6-%-Schalter löste 201-mal aus (Hin und Her) und kostet mehr, als
   er schützt. Die Regel stammt aus einer Studie zu chinesischen Aktien; auf Kryptowährungen mit ihren viel größeren
   Tagesschwankungen wird ein 6-%-Schalter ständig ausgelöst.
6. **Montags-Effekt:** wie die Replikationen: im Mittel unter den Kosten.

## 4. Teil C und D

* **Teil C** (Funding-Raten, Stimmung, On-Chain, Orderbuch, Börsenkalender) ist mit den vorhandenen Kursdaten nicht
  prüfbar. Funding-Raten wären am naheliegendsten (Binance, kostenlos ab 2019); die Quelle `data.binance.vision` ist in
  dieser Umgebung gesperrt. Kein Kandidat dort ist eine reine Spot-Kaufregel, alle bräuchten neue Daten im Bot.
* **Teil D** (Negativliste) deckt sich mit unseren eigenen Messungen: Daytrading nach Tageszeit, BTC-ETH-Lead-Lag,
  gleitende Durchschnitte auf Altcoin-Körben und kurzfristiges Momentum tragen nach Kosten nicht.

## 5. Teil E: Zinsen auf ungenutztes USDC

Gemessen mit der Simulation (`live_reference.py --cash`): Die Kombi ist im Mittel **27 %** investiert (seit 2025: 29 %)
und liegt **40 % der Zeit** fast ganz in USDC. Rund 100 von 150 USDC liegen also meist ungenutzt.

| | |
|---|---|
| Möglichkeit | Binance Simple Earn „USDC Flexible“ (laut Gemini 9,17 % APR inkl. Bonus-Stufe am 08.11.2026 – **nicht geprüft**; der Satz ändert sich täglich, Bonus-Stufen gelten meist nur für kleine Beträge) |
| Ertrag | bei 100 USDC etwa **3,5–9 USDC pro Jahr** (laut Gemini ohne Aktionsbonus 3,61 % für „USDC RWA Flexible“, 3,37 % für feste Laufzeit – nicht geprüft) |
| Risiken | Rücknahme-Verzögerung „bei extremer Marktvolatilität“ – genau dann, wenn der Crash-Kauf Geld braucht; Gegenparteirisiko (Binance verleiht das Geld weiter); tägliche Rücknahmegrenzen |
| Was der Bot dafür bräuchte | Earn-Guthaben ins Kapital einrechnen (sonst sieht er eine Auszahlung und kauft zu klein), vor jedem Kauf zurückholen, eine feste Barreserve für Crash-Käufe halten |

Das ist der einzige Vorschlag, dessen Ertrag nicht vom Markt abhängt. Er ist klein und bringt neue Fehlerquellen in den
Order-Weg. Umgesetzt ist er nicht; ob er es wert ist, ist eine Entscheidung des Betreibers.

## Nachrechnen

```bash
python -I lab/research.py /tmp/kurse/cache /tmp/kurse/cache1m /tmp/lab-out      # alle 13 Familien + Ergänzungsprüfung
python -I lab/live_reference.py /tmp/kurse/cache /tmp/kurse/cache1m --cash      # investierter Anteil der Kombi
```

Die Ergänzungsprüfung steht am Ende der Ausgabe von `research.py` und in `results.json` unter `blend_2b`.
