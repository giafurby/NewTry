import math

import pytest

import strategy
from fakes import SIGNAL_CLOSE_MS, SIGNAL_TS, TF, trend_candles


def test_ema_matches_pandas_definition():
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    result = strategy.ema(values, 3)
    alpha = 0.5
    expected = [1.0]
    for v in values[1:]:
        expected.append(alpha * v + (1 - alpha) * expected[-1])
    assert result[:2] == [None, None]                       # min_periods = span
    assert result[2:] == pytest.approx(expected[2:])


def test_wilder_atr_seed_and_smoothing():
    highs = [10, 11, 12, 13, 14]
    lows = [9, 10, 11, 12, 13]
    closes = [9.5, 10.5, 11.5, 12.5, 13.5]
    atr = strategy.wilder_atr(highs, lows, closes, period=3)
    tr = [1.0, 1.5, 1.5, 1.5, 1.5]                          # max(H-L, |H-Cprev|, |L-Cprev|)
    seed = sum(tr[:3]) / 3
    assert atr[:2] == [None, None]
    assert atr[2] == pytest.approx(seed)
    assert atr[3] == pytest.approx((seed * 2 + tr[3]) / 3)


def test_breakout_above_100_bar_high_and_ema_is_a_signal():
    candles = strategy.closed_candles(trend_candles(SIGNAL_TS), SIGNAL_CLOSE_MS + 60_000)
    check = strategy.evaluate("ETH/USDC", candles)
    assert check.signal, check.reason
    assert check.candle_ts == SIGNAL_TS
    assert check.close > check.prior_high and check.close > check.ema200
    atr_fraction = check.atr / check.close
    assert check.stop_fraction == pytest.approx(2 * atr_fraction)
    assert check.target_fraction == pytest.approx(15 * atr_fraction)
    assert 0.002 <= check.stop_fraction <= 0.10


def test_no_breakout_no_signal():
    candles = strategy.closed_candles(trend_candles(SIGNAL_TS, breakout=False), SIGNAL_CLOSE_MS + 60_000)
    check = strategy.evaluate("ETH/USDC", candles)
    assert not check.signal
    assert check.reason == "kein Ausbruch"
    assert check.gap_pct > 0


def test_breakout_below_ema_200_is_not_bought():
    candles = []
    price = 300.0
    for i in range(900):                                    # langer Abwärtstrend: EMA 200 weit über dem Kurs
        candles.append([SIGNAL_TS - (999 - i) * TF, price, price * 1.002, price * 0.998, price * 0.997, 1.0])
        price *= 0.997
    for i in range(900, 1000):                              # 100 Kerzen seitwärts
        candles.append([SIGNAL_TS - (999 - i) * TF, price, price * 1.003, price * 0.997, price, 1.0])
    candles[-1][4] = price * 1.02                           # Ausbruch über das Seitwärts-Hoch
    candles[-1][2] = price * 1.021
    check = strategy.evaluate("ETH/USDC", candles)
    assert not check.signal
    assert "EMA 200" in check.reason


def test_too_volatile_is_skipped():
    candles = trend_candles(SIGNAL_TS, include_open=False)
    for c in candles:                                       # riesige Kerzen: ATR ~ 8 % -> Stop ~16 % > 10 %
        c[2] = c[4] * 1.04
        c[3] = c[4] * 0.96
    prior_high = max(c[2] for c in candles[-101:-1])
    candles[-1][4] = prior_high * 1.01
    candles[-1][2] = candles[-1][4] * 1.04
    check = strategy.evaluate("ETH/USDC", candles)
    assert not check.signal
    assert "schwankungsreich" in check.reason


def test_too_few_candles():
    check = strategy.evaluate("NEW/USDC", trend_candles(SIGNAL_TS, n=150, include_open=False))
    assert not check.signal and not check.has_data


def test_closed_candles_drops_running_candle():
    candles = trend_candles(SIGNAL_TS)
    closed = strategy.closed_candles(candles, SIGNAL_CLOSE_MS + 1)
    assert closed[-1][0] == SIGNAL_TS
    assert len(closed) == len(candles) - 1


def test_exit_reasons_and_deadline():
    deadline = strategy.deadline_ms(SIGNAL_TS)
    assert deadline == SIGNAL_CLOSE_MS + 120 * TF
    assert strategy.exit_reason(90, 150, deadline, 89.9, SIGNAL_CLOSE_MS) == "Stop"
    assert strategy.exit_reason(90, 150, deadline, 150.0, SIGNAL_CLOSE_MS) == "Ziel"
    assert strategy.exit_reason(90, 150, deadline, 100.0, deadline).startswith("Zeit-Stop")
    assert strategy.exit_reason(90, 150, deadline, 100.0, deadline - 1) is None


def test_entry_window_is_24_minutes():
    assert strategy.ENTRY_WINDOW_MS == 24 * 60 * 1000
    assert math.isclose(strategy.TIMEFRAME_MS, 4 * 3600 * 1000)
