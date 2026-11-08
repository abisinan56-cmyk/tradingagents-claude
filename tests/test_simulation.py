from dataclasses import dataclass
import math

import pytest

from ta_claude.simulation import backtest_strategy, simulate


@dataclass
class Bar:
    day: str
    close: float
    open: float | None = None
    high: float | None = None
    low: float | None = None


def test_signal_fills_next_open_and_charges_turnover_cost():
    bars = [Bar("2026-01-01", 100, 100), Bar("2026-01-02", 110, 105), Bar("2026-01-03", 110, 110)]
    result = simulate("TEST", bars, bars[0].day, bars[-1].day, "fixed", lambda history: 1, cost_bps=100)
    expected = (1 - .01) * (110 / 105) - 1
    assert result.total_return_pct == pytest.approx(expected * 100, abs=.001)
    assert result.turnover_events == 1
    assert result.trades == 1
    assert result.warnings[0].startswith("Signals use completed closes")


def test_end_boundary_excludes_later_bars_and_out_of_range_fills():
    bars = [Bar("2026-01-01", 100, 100), Bar("2026-01-02", 100, 100),
            Bar("2026-01-03", float("nan"), float("nan")),
            Bar("2026-01-04", 2000, 1000)]
    signal = lambda history: 1
    sliced = simulate("TEST", bars[:2], "2026-01-01", "2026-01-02", "fixed", signal)
    full = simulate("TEST", bars, "2026-01-01", "2026-01-02", "fixed", signal)
    assert full == sliced
    assert full.observations == 2
    assert full.total_return_pct == -0.1


def test_overnight_gap_belongs_to_position_held_before_open():
    bars = [Bar("2026-01-01", 100, 100), Bar("2026-01-02", 110, 105), Bar("2026-01-03", 132, 120)]
    result = simulate("TEST", bars, bars[0].day, bars[-1].day, "long", lambda history: 1)
    # The first position fills at 105; it earns the second day's open-to-close move,
    # and the later close-to-open gap while it was still held.
    expected = (1 - .001) * (110 / 105) * (120 / 110) * (132 / 120)
    assert result.total_return_pct == pytest.approx((expected - 1) * 100, abs=.001)


def test_exit_turnover_charges_both_entry_and_exit_costs():
    bars = [Bar("2026-01-01", 100, 100), Bar("2026-01-02", 110, 105),
            Bar("2026-01-03", 120, 120)]
    signal = lambda history: 1 if len(history) == 1 else 0
    result = simulate("TEST", bars, bars[0].day, bars[-1].day, "round_trip", signal, cost_bps=100)
    expected = (1 - .01) * (110 / 105) * (120 / 110) * (1 - .01)
    assert result.total_return_pct == pytest.approx((expected - 1) * 100, abs=.001)
    assert result.turnover_events == 2
    assert result.trades == 1


def test_reversal_charges_two_legs_on_pre_fill_equity():
    bars = [Bar("2026-01-01", 100, 100), Bar("2026-01-02", 100, 100),
            Bar("2026-01-03", 100, 100)]
    signal = lambda history: 1 if len(history) == 1 else -1
    result = simulate("TEST", bars, bars[0].day, bars[-1].day, "reversal", signal, cost_bps=100)
    assert result.total_return_pct == pytest.approx(((1 - .01) * (1 - .02) - 1) * 100, abs=.001)
    assert result.turnover_events == 3


def test_sharpe_uses_arithmetic_daily_returns_and_zero_risk_free_rate():
    bars = [Bar("2026-01-01", 100, 100), Bar("2026-01-02", 110, 100), Bar("2026-01-03", 99, 110)]
    result = simulate("TEST", bars, bars[0].day, bars[-1].day, "long", lambda history: 1, cost_bps=0)
    # Daily returns are [0, +10%, -10%], so the arithmetic excess mean is zero.
    assert result.sharpe == 0


def test_zero_volatility_sharpe_is_none_and_flat_position_stays_finite():
    bars = [Bar("2026-01-01", 100), Bar("2026-01-02", 110), Bar("2026-01-03", 121)]
    bars = [Bar(bar.day, bar.close, bar.close) for bar in bars]
    result = simulate("TEST", bars, bars[0].day, bars[-1].day, "flat", lambda history: 0)
    assert result.sharpe is None
    assert result.total_return_pct == 0
    assert all(value is None or math.isfinite(value) for value in (
        result.total_return_pct, result.annualized_return_pct, result.annualized_volatility_pct,
        result.sharpe, result.max_drawdown_pct, result.buy_and_hold_return_pct))


def test_requested_bar_with_missing_open_is_rejected():
    bars = [Bar("2026-03-01", 100, 100), Bar("2026-03-02", 110),
            Bar("2026-03-03", 121, 110)]
    with pytest.raises(ValueError, match="Requested bar 2026-03-02 is missing an open"):
        simulate("TEST", bars, bars[0].day, bars[-1].day, "long", lambda history: 1)


def test_cagr_sample_volatility_and_close_drawdown_are_consistent():
    bars = [Bar("2026-04-01", 100, 100), Bar("2026-04-02", 110, 100),
            Bar("2026-04-03", 99, 110)]
    result = simulate("TEST", bars, bars[0].day, bars[-1].day, "long", lambda history: 1, cost_bps=0)
    expected_daily_returns = [0.0, 0.10, -0.10]
    expected_annualized_vol = math.sqrt(sum((r - 0) ** 2 for r in expected_daily_returns) / 2) * math.sqrt(252)
    assert result.total_return_pct == pytest.approx(-1.0)
    assert result.annualized_return_pct == pytest.approx(((.99 ** (252 / 3)) - 1) * 100, abs=.001)
    assert result.annualized_volatility_pct == pytest.approx(expected_annualized_vol * 100, abs=.001)
    assert result.max_drawdown_pct == pytest.approx(-10.0)
    assert "cannot capture intraday lows" in result.warnings[-2]


def test_strategy_adapter_uses_callback_and_validates_dates_and_signals():
    bars = [Bar(f"2026-02-0{i}", 100, 100) for i in range(1, 4)]
    result = backtest_strategy(bars, "2026-02-01", "2026-02-03", "custom", lambda history: 0)
    assert result.observations == 3
    with pytest.raises(ValueError, match="start must not be after end"):
        simulate("TEST", bars, "2026-02-03", "2026-02-01", "flat", lambda history: 0)
    with pytest.raises(ValueError, match="Signal must return"):
        simulate("TEST", bars, "2026-02-01", "2026-02-03", "bad", lambda history: 2)
