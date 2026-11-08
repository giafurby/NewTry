"""
Simulationsmaschine des Forschungslabors (numba). Alle Strategien laufen hier unter IDENTISCHEN Bedingungen:

  * eine 15-Minuten-Zeitachse für alle Coins, Kapital 1,0 am Start, Bewertung jeder Kerze (Rückgang auch innerhalb des Tages)
  * Entscheidung auf dem Schluss der Kerze i, Ausführung in Kerze i+1 zum Preis EP[i+1] (2. Minute, siehe data.py)
  * Kosten je Seite `cost` (Gebühr + Spread + Schlupf), auf jeden gehandelten Betrag
  * Stop: Tief <= Stop -> Verkauf zu min(Stop, Eröffnung) (Kurslücke zählt voll); Ziel: Hoch >= Ziel -> max(Ziel, Eröffnung)
  * innerhalb einer Kerze gilt der Stop vor dem Ziel (ungünstigster Fall); in der Einstiegskerze nie die Eröffnung
  * nur Spot, kein Hebel, keine Leerverkäufe: gekauft wird nur mit freiem Geld

Drei Bausteine:
  sim_trades    einzelne Trades (Einstiegssignal + Stop/Ziel/Zeit/Trailing/Teilverkauf), z. B. Trend-Ausbruch, Crash-Kauf
  sim_weights   Zielgewichte, die zu festen Zeitpunkten umgeschichtet werden (Momentum, Trendfilter, Halten)
  sim_tranches  gestaffelte Käufe in bis zu drei Tranchen mit Ausstieg am Durchschnittspreis
"""
from __future__ import annotations

import numpy as np
from numba import njit

# Ausstiegsgründe in den Trade-Listen
R_STOP, R_TARGET, R_TIME, R_TRAIL, R_PART, R_SIGNAL, R_END = 1, 2, 3, 4, 5, 6, 7


@njit(cache=True)
def sim_trades(O, H, L, CF, EP, sig, prio, stopf, tgtf, trailf, hold, part_frac, part_tgt, size_mode, size_a, size_cap,
               kmax, cost, cooldown, start, end, min_frac, exit_sig, extend):
    """
    sig[i, j]     Einstiegssignal auf dem Schluss von Kerze i
    prio[i, j]    Reihenfolge bei mehreren Signalen in derselben Kerze (größer zuerst)
    stopf[i, j]   Stop-Abstand als Anteil (NaN = kein Stop); tgtf = Ziel-Abstand (inf = keins); trailf = Trailing-Abstand
                  als Anteil vom Höchstkurs seit Einstieg (0 = aus)
    hold          Zeit-Ausstieg: Schluss der Kerze Einstieg + hold - 1
    part_frac     Anteil, der bei +part_tgt verkauft wird (0 = aus); danach Stop auf Einstand
    size_mode     0: size_a des Kapitals; 1: Risiko size_a / Stop-Abstand
    size_cap      höchstens dieser Anteil des Kapitals je Position; kmax Positionen gleichzeitig
    cooldown      Kerzen Sperre für den Coin nach einem Stop
    exit_sig[i,j] zusätzlicher Ausstieg auf dem Schluss von Kerze i (z. B. Trendwechsel)
    extend        True: Besteht das Einstiegssignal am Ende der Haltedauer erneut, läuft die Position um `hold` Kerzen
                  weiter (kein Verkauf und Neukauf, keine Kosten)
    Rückgabe: Kapitalkurve (N), Trades (n, 8): Einstiegskerze, Ausstiegskerze, Coin, Einstieg, Ausstieg, Rendite netto,
              Grund, Kapitalanteil
    """
    N, K = O.shape
    eq = np.full(N, np.nan)
    cash = 1.0
    inpos = np.zeros(K, np.bool_)
    units = np.zeros(K)
    entry = np.zeros(K)
    stop = np.zeros(K)
    tgt = np.zeros(K)
    trail = np.zeros(K)
    peak = np.zeros(K)
    ebar = np.zeros(K, np.int64)
    deadline = np.zeros(K, np.int64)
    parted = np.zeros(K, np.bool_)
    cost_in = np.zeros(K)          # eingesetztes Geld (für die Trade-Rendite)
    got = np.zeros(K)              # bereits erlöstes Geld (Teilverkauf)
    weight = np.zeros(K)
    blocked = np.zeros(K, np.int64)
    cap = 400_000
    tr = np.zeros((cap, 8))
    nt = 0
    npos = 0
    order = np.zeros(K, np.int64)
    for i in range(start, end):
        # ---------------------------------------------------------------- Ausstiege in Kerze i
        for j in range(K):
            if not inpos[j] or i < ebar[j]:
                continue
            lo = L[i, j]
            hi = H[i, j]
            op = O[i, j]
            first = i == ebar[j]
            px = np.nan
            reason = 0
            if lo == lo:
                if lo <= stop[j]:
                    px = stop[j] if first else min(stop[j], op)
                    reason = R_TRAIL if stop[j] >= entry[j] else R_STOP
                elif part_frac > 0.0 and not parted[j] and hi >= entry[j] * (1.0 + part_tgt):
                    ppx = entry[j] * (1.0 + part_tgt)
                    if not first:
                        ppx = max(ppx, op)
                    sold = units[j] * part_frac
                    cash += sold * ppx * (1.0 - cost)
                    got[j] += sold * ppx * (1.0 - cost)
                    units[j] -= sold
                    parted[j] = True
                    stop[j] = max(stop[j], entry[j] * (1.0 + 2.0 * cost))      # Rest auf Einstand inkl. Kosten
                if px != px and hi >= tgt[j]:
                    px = tgt[j] if first else max(tgt[j], op)
                    reason = R_TARGET
                if px != px:
                    if hi > peak[j]:
                        peak[j] = hi
                    if trail[j] > 0.0:
                        ns = peak[j] * (1.0 - trail[j])
                        if ns > stop[j]:
                            stop[j] = ns
            if px != px and i >= deadline[j] and extend and sig[i, j]:
                deadline[j] = i + hold
            if px != px and i >= deadline[j] and CF[i, j] == CF[i, j]:
                px = CF[i, j]
                reason = R_TIME
            if px != px and exit_sig[i, j] and CF[i, j] == CF[i, j]:
                px = CF[i, j]
                reason = R_SIGNAL
            if px == px:
                proceeds = units[j] * px * (1.0 - cost)
                cash += proceeds
                if nt < cap:
                    tr[nt, 0] = ebar[j]
                    tr[nt, 1] = i
                    tr[nt, 2] = j
                    tr[nt, 3] = entry[j]
                    tr[nt, 4] = px
                    tr[nt, 5] = (got[j] + proceeds) / cost_in[j] - 1.0
                    tr[nt, 6] = reason
                    tr[nt, 7] = weight[j]
                    nt += 1
                inpos[j] = False
                units[j] = 0.0
                npos -= 1
                if reason == R_STOP and cooldown > 0:
                    blocked[j] = i + cooldown
        # ---------------------------------------------------------------- Bewertung
        val = cash
        for j in range(K):
            if inpos[j]:
                c = CF[i, j]
                val += units[j] * (c if c == c else entry[j])
        eq[i] = val
        # ---------------------------------------------------------------- Einstiege (Schluss Kerze i -> Kerze i+1)
        if npos >= kmax or i + 1 >= N:
            continue
        m = 0
        for j in range(K):
            if sig[i, j] and not inpos[j] and i >= blocked[j] and EP[i + 1, j] == EP[i + 1, j]:
                order[m] = j
                m += 1
        if m == 0:
            continue
        # einfache Sortierung nach prio (absteigend)
        for a in range(m):
            for b in range(a + 1, m):
                if prio[i, order[b]] > prio[i, order[a]]:
                    tmp = order[a]
                    order[a] = order[b]
                    order[b] = tmp
        for q in range(m):
            if npos >= kmax:
                break
            j = order[q]
            sf = stopf[i, j]
            if size_mode == 1:
                if not (sf > 0.0):
                    continue
                budget = val * size_a / sf
            else:
                budget = val * size_a
            budget = min(budget, val * size_cap, cash)
            if budget < val * min_frac or budget <= 0.0:
                continue
            ep = EP[i + 1, j]
            cash -= budget
            inpos[j] = True
            npos += 1
            units[j] = budget * (1.0 - cost) / ep
            entry[j] = ep
            stop[j] = ep * (1.0 - sf) if sf == sf else -1.0
            tgt[j] = ep * (1.0 + tgtf[i, j])
            trail[j] = trailf[i, j]
            peak[j] = ep
            ebar[j] = i + 1
            deadline[j] = i + hold
            parted[j] = False
            cost_in[j] = budget
            got[j] = 0.0
            weight[j] = budget / val
    # offene Positionen am Ende zum letzten Schluss bewerten (nicht als Trade gezählt)
    return eq, tr[:nt]


@njit(cache=True)
def sim_weights(CF, EP, W, rebal, cost, band, start, end):
    """
    Zielgewichte W[r, j] (Summe <= 1), entschieden auf dem Schluss der Kerze rebal[r], ausgeführt zu EP[rebal[r] + 1].
    Gehandelt wird nur, wenn das Gewicht um mehr als `band` abweicht oder auf 0 soll. Verkäufe vor Käufen.
    Rückgabe: Kapitalkurve, Umschlag (Summe gehandelter Anteile), Anzahl Orders.
    """
    N, K = CF.shape
    eq = np.full(N, np.nan)
    cash = 1.0
    units = np.zeros(K)
    r = 0
    R = len(rebal)
    while r < R and rebal[r] < start:
        r += 1
    turnover = 0.0
    orders = 0
    for i in range(start, end):
        val = cash
        for j in range(K):
            if units[j] > 0.0:
                c = CF[i, j]
                if c == c:
                    val += units[j] * c
        eq[i] = val
        if r < R and rebal[r] == i and i + 1 < N:
            px = np.empty(K)
            pv = cash
            for j in range(K):
                p = EP[i + 1, j]
                if p != p:
                    p = CF[i, j]
                px[j] = p
                if units[j] > 0.0 and p == p:
                    pv += units[j] * p
            # Verkäufe
            for j in range(K):
                if units[j] <= 0.0 or px[j] != px[j]:
                    continue
                cur = units[j] * px[j] / pv
                tw = W[r, j]
                if tw != tw:
                    tw = 0.0
                if cur - tw > band or (tw <= 0.0 and cur > 0.0):
                    sell = (cur - tw) * pv
                    if tw <= 0.0:
                        sell = units[j] * px[j]
                    units[j] -= sell / px[j]
                    if units[j] < 1e-15:
                        units[j] = 0.0
                    cash += sell * (1.0 - cost)
                    turnover += sell / pv
                    orders += 1
            # Käufe
            for j in range(K):
                if px[j] != px[j]:
                    continue
                cur = units[j] * px[j] / pv
                tw = W[r, j]
                if tw != tw or tw <= 0.0:
                    continue
                if tw - cur > band or (cur <= 0.0 and tw > 0.0):
                    buy = min((tw - cur) * pv, cash)
                    if buy <= pv * 0.002:
                        continue
                    cash -= buy
                    units[j] += buy * (1.0 - cost) / px[j]
                    turnover += buy / pv
                    orders += 1
            r += 1
    return eq, turnover, orders


@njit(cache=True)
def sim_tranches(O, H, L, C, CF, EP, sig1, rev, vspike, d2, d3, fr, tp, hard_stop, stop_check, exit_sig, pos_frac, kmax,
                 cost, start, end):
    """
    Gestaffelter Kauf je Coin (bis zu drei Tranchen):
      Tranche 1: sig1 auf dem Schluss
      Tranche 2: Schluss <= Preis der Tranche 1 × (1 − d2) und rev (Umkehrkerze)
      Tranche 3: Schluss <= Preis der Tranche 1 × (1 − d3) und vspike (Volumen-Spitze)
    Größe je Tranche: fr[k] × pos_frac × Kapital. Ausstieg: Hoch >= Durchschnitt × (1 + tp); exit_sig auf dem Schluss;
    harter Stop: Schluss <= Durchschnitt × (1 − hard_stop) auf Kerzen mit stop_check (z. B. 4h-Schluss).
    """
    N, K = O.shape
    eq = np.full(N, np.nan)
    cash = 1.0
    units = np.zeros(K)
    spent = np.zeros(K)
    level = np.zeros(K, np.int64)
    first_px = np.zeros(K)
    first_bar = np.zeros(K, np.int64)
    last_add = np.zeros(K, np.int64)
    cap = 400_000
    tr = np.zeros((cap, 8))
    nt = 0
    npos = 0
    for i in range(start, end):
        for j in range(K):
            if level[j] == 0 or i <= last_add[j]:
                continue
            avg = spent[j] * (1.0 - cost) / units[j]
            px = np.nan
            reason = 0
            hi = H[i, j]
            if hi == hi and hi >= avg * (1.0 + tp):
                px = max(avg * (1.0 + tp), O[i, j])
                reason = R_TARGET
            c = C[i, j]
            if px != px and stop_check[i] and c == c and c <= avg * (1.0 - hard_stop):
                px = c
                reason = R_STOP
            if px != px and exit_sig[i, j] and c == c:
                px = c
                reason = R_SIGNAL
            if px == px:
                proceeds = units[j] * px * (1.0 - cost)
                cash += proceeds
                if nt < cap:
                    tr[nt, 0] = first_bar[j]
                    tr[nt, 1] = i
                    tr[nt, 2] = j
                    tr[nt, 3] = avg
                    tr[nt, 4] = px
                    tr[nt, 5] = proceeds / spent[j] - 1.0
                    tr[nt, 6] = reason
                    tr[nt, 7] = level[j]
                    nt += 1
                units[j] = 0.0
                spent[j] = 0.0
                level[j] = 0
                npos -= 1
        val = cash
        for j in range(K):
            if level[j] > 0:
                val += units[j] * CF[i, j]
        eq[i] = val
        if i + 1 >= N:
            continue
        for j in range(K):
            ep = EP[i + 1, j]
            c = C[i, j]
            if ep != ep or c != c:
                continue
            want = -1
            if level[j] == 0 and sig1[i, j] and npos < kmax:
                want = 0
            elif level[j] == 1 and rev[i, j] and c <= first_px[j] * (1.0 - d2):
                want = 1
            elif level[j] == 2 and vspike[i, j] and c <= first_px[j] * (1.0 - d3):
                want = 2
            if want < 0:
                continue
            budget = min(val * pos_frac * fr[want], cash)
            if budget < val * pos_frac * fr[want] * 0.5:
                continue
            cash -= budget
            units[j] += budget * (1.0 - cost) / ep
            spent[j] += budget
            if want == 0:
                npos += 1
                first_bar[j] = i + 1
                first_px[j] = ep
            level[j] = want + 1
            last_add[j] = i + 1
    return eq, tr[:nt]


@njit(cache=True)
def sim_joint(O, H, L, CF, EP, sigA, stopA, tgtA, holdA, riskA, capA, kA, minA,
              sigB, stopB, holdB, sizeB, kB, coolB, cost, start, end):
    """
    Gemeinsames Depot wie im NewTry-Bot: Regel A (Trend, Größe = Risiko / Stop, höchstens capA) und Regel B (Crash-Kauf,
    feste Größe sizeB) teilen sich das freie Geld, je Coin höchstens EINE Position, A wird vor B geprüft.
    Sperre nach Stop nur für B. Rückgabe: Kapitalkurve, Trades (…, Spalte 7 = Art 0/1, Spalte 8 = Anteil des Kapitals).
    """
    N, K = O.shape
    eq = np.full(N, np.nan)
    cash = 1.0
    kind = np.full(K, -1, np.int64)
    units = np.zeros(K)
    entry = np.zeros(K)
    stop = np.zeros(K)
    tgt = np.zeros(K)
    ebar = np.zeros(K, np.int64)
    deadline = np.zeros(K, np.int64)
    cost_in = np.zeros(K)
    wfrac = np.zeros(K)
    blocked = np.zeros(K, np.int64)
    cap = 400_000
    tr = np.zeros((cap, 9))
    nt = 0
    for i in range(start, end):
        for j in range(K):
            if kind[j] < 0 or i < ebar[j]:
                continue
            lo = L[i, j]
            first = i == ebar[j]
            px = np.nan
            reason = 0
            if lo == lo:
                if lo <= stop[j]:
                    px = stop[j] if first else min(stop[j], O[i, j])
                    reason = R_STOP
                elif H[i, j] >= tgt[j]:
                    px = tgt[j] if first else max(tgt[j], O[i, j])
                    reason = R_TARGET
            if px != px and i >= deadline[j] and CF[i, j] == CF[i, j]:
                px = CF[i, j]
                reason = R_TIME
            if px == px:
                proceeds = units[j] * px * (1.0 - cost)
                cash += proceeds
                if nt < cap:
                    tr[nt, 0] = ebar[j]
                    tr[nt, 1] = i
                    tr[nt, 2] = j
                    tr[nt, 3] = entry[j]
                    tr[nt, 4] = px
                    tr[nt, 5] = proceeds / cost_in[j] - 1.0
                    tr[nt, 6] = reason
                    tr[nt, 7] = kind[j]
                    tr[nt, 8] = wfrac[j]
                    nt += 1
                if kind[j] == 1 and reason == R_STOP and coolB > 0:
                    blocked[j] = i + coolB
                kind[j] = -1
                units[j] = 0.0
        val = cash
        nA = 0
        nB = 0
        for j in range(K):
            if kind[j] >= 0:
                c = CF[i, j]
                val += units[j] * (c if c == c else entry[j])
                if kind[j] == 0:
                    nA += 1
                else:
                    nB += 1
        eq[i] = val
        if i + 1 >= N:
            continue
        for rule in range(2):
            for j in range(K):
                if kind[j] >= 0:
                    continue
                ep = EP[i + 1, j]
                if ep != ep:
                    continue
                if rule == 0:
                    if nA >= kA or not sigA[i, j]:
                        continue
                    sf = stopA[i, j]
                    if not (sf > 0.0):
                        continue
                    budget = min(val * riskA / sf, val * capA, cash)
                    if budget < val * minA:
                        continue
                    tg = ep * (1.0 + tgtA[i, j])
                    hold = holdA
                else:
                    if nB >= kB or not sigB[i, j] or i < blocked[j]:
                        continue
                    sf = stopB
                    budget = min(val * sizeB, cash)
                    if budget < val * sizeB * 0.5:
                        continue
                    tg = np.inf
                    hold = holdB
                cash -= budget
                kind[j] = rule
                units[j] = budget * (1.0 - cost) / ep
                entry[j] = ep
                stop[j] = ep * (1.0 - sf)
                tgt[j] = tg
                ebar[j] = i + 1
                deadline[j] = i + hold
                cost_in[j] = budget
                wfrac[j] = budget / val
                if rule == 0:
                    nA += 1
                else:
                    nB += 1
    return eq, tr[:nt]


@njit(cache=True)
def sim_weights_dd(CF, EP, W, rebal, cost, band, dd_max, cool_bars, start, end):
    """
    Wie sim_weights, dazu ein Drawdown-Schalter auf das Modul-Kapital: Fällt es in irgendeiner Kerze mehr als dd_max unter
    seinen Höchststand, wird alles zum Schluss dieser Kerze verkauft und `cool_bars` Kerzen nicht gehandelt. Danach gilt der
    aktuelle Wert als neuer Höchststand; gekauft wird ab dem nächsten regulären Umschichtungstermin.
    Rückgabe: Kapitalkurve, Umschlag, Anzahl Orders, Anzahl Auslösungen.
    """
    N, K = CF.shape
    eq = np.full(N, np.nan)
    cash = 1.0
    units = np.zeros(K)
    r = 0
    R = len(rebal)
    while r < R and rebal[r] < start:
        r += 1
    turnover = 0.0
    orders = 0
    trips = 0
    peak = 1.0
    cool_until = -1
    for i in range(start, end):
        val = cash
        for j in range(K):
            if units[j] > 0.0:
                c = CF[i, j]
                if c == c:
                    val += units[j] * c
        if i == cool_until:
            peak = val
        if val > peak:
            peak = val
        if i >= cool_until and val < peak * (1.0 - dd_max):
            for j in range(K):
                if units[j] > 0.0:
                    c = CF[i, j]
                    cash += units[j] * c * (1.0 - cost)
                    turnover += units[j] * c / val
                    units[j] = 0.0
                    orders += 1
            val = cash
            trips += 1
            cool_until = i + cool_bars
        eq[i] = val
        while r < R and rebal[r] < i:
            r += 1
        if r < R and rebal[r] == i and i + 1 < N:
            if i >= cool_until:
                px = np.empty(K)
                pv = cash
                for j in range(K):
                    p = EP[i + 1, j]
                    if p != p:
                        p = CF[i, j]
                    px[j] = p
                    if units[j] > 0.0 and p == p:
                        pv += units[j] * p
                for j in range(K):
                    if units[j] <= 0.0 or px[j] != px[j]:
                        continue
                    cur = units[j] * px[j] / pv
                    tw = W[r, j]
                    if tw != tw:
                        tw = 0.0
                    if cur - tw > band or (tw <= 0.0 and cur > 0.0):
                        sell = (cur - tw) * pv
                        if tw <= 0.0:
                            sell = units[j] * px[j]
                        units[j] -= sell / px[j]
                        if units[j] < 1e-15:
                            units[j] = 0.0
                        cash += sell * (1.0 - cost)
                        turnover += sell / pv
                        orders += 1
                for j in range(K):
                    if px[j] != px[j]:
                        continue
                    cur = units[j] * px[j] / pv
                    tw = W[r, j]
                    if tw != tw or tw <= 0.0:
                        continue
                    if tw - cur > band or (cur <= 0.0 and tw > 0.0):
                        buy = min((tw - cur) * pv, cash)
                        if buy <= pv * 0.002:
                            continue
                        cash -= buy
                        units[j] += buy * (1.0 - cost) / px[j]
                        turnover += buy / pv
                        orders += 1
            r += 1
    return eq, turnover, orders, trips
