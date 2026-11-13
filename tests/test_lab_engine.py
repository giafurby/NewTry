"""Forschungsmaschine (lab/engine.py) auf kleinen, von Hand nachrechenbaren Kursreihen. Ohne numba übersprungen."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")             # der Bot selbst braucht weder numpy noch numba (CI ohne Labor-Pakete)
pytest.importorskip("numba")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lab"))
import engine  # noqa: E402


def flat(n=40, k=1, price=100.0):
    O = np.full((n, k), price)
    return O, O.copy(), O.copy(), O.copy()


def run(O, H, L, C, sig, stopf=0.1, tgtf=np.inf, hold=5, cost=0.0, size=1.0, EP=None):
    n, k = O.shape
    EP = O if EP is None else EP
    z = np.zeros((n, k))
    return engine.sim_trades(O, H, L, C, EP, sig, z, np.full((n, k), stopf), np.full((n, k), tgtf), z, hold, 0.0, 0.0,
                             0, size, size, 3, cost, 0, 0, n, 0.0, np.zeros((n, k), bool), False)


def test_time_exit_after_hold_bars_and_costs_on_both_sides():
    O, H, L, C = flat()
    sig = np.zeros((40, 1), bool)
    sig[10, 0] = True
    C[10 + 5:, 0] = 110.0                                     # ab Ausstiegskerze 15 (Einstieg 11, 5 Kerzen) höher
    eq, tr = run(O, H, L, C, sig, cost=0.001)
    assert len(tr) == 1
    entry_bar, exit_bar, _, entry, exit_, ret, reason, _ = tr[0]
    assert (entry_bar, exit_bar, reason) == (11, 15, engine.R_TIME)
    assert entry == 100.0 and exit_ == 110.0
    assert ret == pytest.approx(1.1 * 0.999 * 0.999 - 1)
    assert eq[-1] == pytest.approx(1.1 * 0.999 * 0.999)


def test_stop_fills_at_gap_open_and_stop_beats_target_in_same_bar():
    O, H, L, C = flat()
    sig = np.zeros((40, 1), bool)
    sig[10, 0] = True
    O[13, 0], L[13, 0], H[13, 0] = 80.0, 79.0, 130.0          # Kurslücke unter den Stop, Hoch über dem Ziel
    eq, tr = run(O, H, L, C, sig, stopf=0.1, tgtf=0.2, hold=20)
    assert tr[0][6] == engine.R_STOP and tr[0][4] == 80.0     # zum Eröffnungskurs, nicht zum Stop
    O, H, L, C = flat()
    H[13, 0] = 125.0
    eq, tr = run(O, H, L, C, sig, stopf=0.1, tgtf=0.2, hold=20)
    assert tr[0][6] == engine.R_TARGET and tr[0][4] == pytest.approx(120.0)


def test_entry_uses_execution_price_not_close():
    O, H, L, C = flat()
    EP = O.copy()
    EP[11, 0] = 101.0                                         # 2. Minute der Folgekerze teurer
    sig = np.zeros((40, 1), bool)
    sig[10, 0] = True
    _, tr = run(O, H, L, C, sig, EP=EP)
    assert tr[0][3] == 101.0


def test_joint_depot_without_crash_signals_equals_single_strategy():
    rng = np.random.default_rng(3)
    n, k = 400, 3
    C = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (n, k)), axis=0))
    O = np.vstack([C[:1], C[:-1]])
    H, L = np.maximum(O, C) * 1.002, np.minimum(O, C) * 0.998
    sig = rng.random((n, k)) < 0.02
    stopf = np.full((n, k), 0.03)
    tgtf = np.full((n, k), 0.06)
    z = np.zeros((n, k))
    a, ta = engine.sim_trades(O, H, L, C, O, sig, z, stopf, tgtf, z, 30, 0.0, 0.0, 1, 0.01, 0.33, 3, 0.002, 0, 0, n,
                              0.02, np.zeros((n, k), bool), False)
    b, tb = engine.sim_joint(O, H, L, C, O, sig, stopf, tgtf, 30, 0.01, 0.33, 3, 0.02, np.zeros((n, k), bool), 0.15, 16,
                             0.2, 3, 96, 0.002, 0, n)
    assert len(ta) == len(tb) > 5
    np.testing.assert_allclose(a, b)


def test_leverage_one_equals_the_joint_depot():
    rng = np.random.default_rng(5)
    n, k = 600, 3
    C = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, (n, k)), axis=0))
    O = np.vstack([C[:1], C[:-1]])
    H, L = np.maximum(O, C) * 1.003, np.minimum(O, C) * 0.997
    sigA, sigB = rng.random((n, k)) < 0.02, rng.random((n, k)) < 0.01
    args = (O, H, L, C, O, sigA, np.full((n, k), 0.03), np.full((n, k), 0.08), 30, 0.01, 0.33, 3, 0.02,
            sigB, 0.15, 16, 0.2, 3, 96, 0.002, 0, n)
    a, ta = engine.sim_joint(*args)
    b, liqs, interest = engine.sim_joint_lev(*args, 1.0, 0.0001, 1.1, 0.01)
    assert len(ta) > 10 and liqs == 0 and interest == 0.0     # ohne Kredit keine Zinsen und keine Liquidation
    np.testing.assert_allclose(a, b)


def test_margin_liquidation_comes_before_the_stop():
    n, k = 40, 1
    O, H, L, C = flat(n, k)
    L[20, 0] = 54.0                                         # Tief über dem Stop (50), aber unter der Liquidationsschwelle
    sigA = np.zeros((n, k), bool)
    sigA[10, 0] = True
    eq, liqs, _ = engine.sim_joint_lev(O, H, L, C, O, sigA, np.full((n, k), 0.5), np.full((n, k), 10.0), 30, 1.0, 5.0,
                                       3, 0.0, np.zeros((n, k), bool), 0.15, 16, 0.2, 3, 96, 0.0, 0, n,
                                       5.0, 0.0, 1.1, 0.01)
    # Kauf für 2,0 (Risiko 100 % / Stop 50 %), davon 1,0 geliehen. Beim Tief 54: Vermögen 1,08 ≤ 1,1 × Schulden 1,0
    assert liqs == 1
    assert eq[19] == pytest.approx(1.0)
    assert eq[20] == pytest.approx(-1.0 + 0.02 * 54.0 * 0.99)   # zum Tief verkauft, 1 % Liquidationsgebühr
    assert eq[-1] == pytest.approx(eq[20])


def test_position_is_extended_while_entry_signal_persists():
    O, H, L, C = flat()
    sig = np.zeros((40, 1), bool)
    sig[10, 0] = sig[15, 0] = True                          # Signal am Ende der ersten Haltedauer erneut
    n, k = O.shape
    z = np.zeros((n, k))
    eq, tr = engine.sim_trades(O, H, L, C, O, sig, z, np.full((n, k), 0.1), np.full((n, k), np.inf), z, 5, 0.0, 0.0,
                               0, 1.0, 1.0, 3, 0.001, 0, 0, n, 0.0, np.zeros((n, k), bool), True)
    assert len(tr) == 1 and tr[0][1] == 20                  # ein Trade, verkauft erst am Ende der Verlängerung
    assert eq[-1] == pytest.approx(0.999 * 0.999)           # nur einmal Kosten für Kauf und Verkauf


def test_drawdown_switch_sells_everything_and_waits():
    n = 60
    CF = np.full((n, 1), 100.0)
    CF[20:, 0] = 90.0                                       # −10 % ab Kerze 20
    W = np.ones((3, 1))
    rebal = np.array([5, 25, 45], dtype=np.int64)
    eq, turnover, orders, trips = engine.sim_weights_dd(CF, CF, W, rebal, 0.0, 0.0, 0.06, 10, 0, n)
    assert trips == 1
    assert eq[20] == pytest.approx(0.9) and eq[29] == pytest.approx(0.9)      # ab Kerze 20 in Cash, Pause bis 30
    assert orders == 3                                      # Kauf bei 5, Notverkauf bei 20, Kauf bei 45 (25 in der Pause)
