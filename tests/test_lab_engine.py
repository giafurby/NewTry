"""Forschungsmaschine (lab/engine.py) auf kleinen, von Hand nachrechenbaren Kursreihen. Ohne numba übersprungen."""
import sys
from pathlib import Path

import numpy as np
import pytest

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
                             0, size, size, 3, cost, 0, 0, n, 0.0, np.zeros((n, k), bool))


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
                              0.02, np.zeros((n, k), bool))
    b, tb = engine.sim_joint(O, H, L, C, O, sig, stopf, tgtf, 30, 0.01, 0.33, 3, 0.02, np.zeros((n, k), bool), 0.15, 16,
                             0.2, 3, 96, 0.002, 0, n)
    assert len(ta) == len(tb) > 5
    np.testing.assert_allclose(a, b)
