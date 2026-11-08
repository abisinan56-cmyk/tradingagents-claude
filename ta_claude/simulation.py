"""Next-open daily-bar backtests independent of the application model module."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from statistics import fmean, stdev
from typing import Callable, Sequence


@dataclass(frozen=True)
class SimulationResult:
    ticker: str
    start: str
    end: str
    strategy: str
    cost_bps: float
    observations: int
    trades: int
    turnover_events: int
    win_rate: float | None
    total_return_pct: float
    annualized_return_pct: float | None
    annualized_volatility_pct: float | None
    sharpe: float | None
    max_drawdown_pct: float
    buy_and_hold_return_pct: float
    warnings: list[str] = field(default_factory=list)


Signal = Callable[[Sequence[object]], int]


def _finite_number(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Each bar needs a finite {label}.") from exc
    if not math.isfinite(number):
        raise ValueError(f"Each bar needs a finite {label}.")
    return number


def _validate_inputs(bars: Sequence[object], start: str, end: str, cost_bps: float) -> tuple[list[object], list[object]]:
    try:
        start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    except (TypeError, ValueError) as exc:
        raise ValueError("start and end must be ISO dates.") from exc
    if start_date > end_date:
        raise ValueError("start must not be after end.")
    cost_bps = _finite_number(cost_bps, "cost_bps")
    if cost_bps < 0 or cost_bps >= 10_000:
        raise ValueError("cost_bps must be nonnegative and less than 10000.")

    history: list[object] = []
    requested: list[object] = []
    previous_day: str | None = None
    for bar in bars:
        try:
            day = str(bar.day)
            parsed_day = date.fromisoformat(day)
        except AttributeError as exc:
            raise ValueError("Each bar needs day and close fields.") from exc
        if parsed_day > end_date:
            continue
        try:
            close = _finite_number(bar.close, "close")
        except AttributeError as exc:
            raise ValueError("Each bar needs day and close fields.") from exc
        if previous_day is not None and day <= previous_day:
            raise ValueError("Bars through end must be in strictly increasing date order.")
        previous_day = day
        if close <= 0:
            raise ValueError("Bar prices must be positive.")
        opening = getattr(bar, "open", None)
        if opening is not None:
            opening = _finite_number(opening, "open")
            if opening <= 0:
                raise ValueError("Bar prices must be positive.")
        if parsed_day < start_date:
            history.append(bar)
        else:
            if opening is None:
                raise ValueError(f"Requested bar {day} is missing an open price.")
            requested.append(bar)
    if len(requested) < 2:
        raise ValueError("The requested range needs at least two trading days.")
    return history, requested


def _open(bar: object) -> float:
    value = getattr(bar, "open", None)
    if value is None:
        raise ValueError(f"Requested bar {bar.day} is missing an open price.")
    return _finite_number(value, "open")


def simulate(ticker: str, bars: Sequence[object], start: str, end: str, strategy: str,
             signal: Signal, cost_bps: float = 10.0) -> SimulationResult:
    """Simulate a -1/0/+1 signal, formed after close and filled at the next open.

    The first requested open is the initial valuation point. Existing positions earn
    the close-to-next-open gap; the newly selected position earns open-to-close.
    Requested bars must have opens. Cost is charged per unit of absolute position
    change at each fill. Exposure is
    100% of equity, shorts are unlevered, financing is excluded, and
    positions are marked, not liquidated, at the final close. Open and close prices
    must use a consistent adjustment basis. Sharpe uses arithmetic daily excess
    returns with a zero risk-free rate. Drawdown is measured from daily closes;
    OHLC bars cannot establish the intraday price path.
    """
    history, requested = _validate_inputs(bars, start, end, cost_bps)
    cost_fraction = cost_bps / 10_000
    equity = 1.0
    position = 0
    daily_returns: list[float] = []
    turnover_events = 0
    trades = 0
    trade_factor: float | None = None
    closed_trade_returns: list[float] = []

    for index, bar in enumerate(requested):
        equity_at_previous_close = equity
        prior_close = float(history[-1].close) if index == 0 and history else (
            float(requested[index - 1].close) if index else _open(bar))
        opening = _open(bar)
        close = float(bar.close)
        has_previous = index > 0 or bool(history)
        gap_return = opening / prior_close - 1 if has_previous else 0.0
        if not math.isfinite(gap_return):
            raise ValueError("Price data produced a non-finite overnight return.")
        gap_factor = 1 + position * gap_return
        if gap_factor <= 0:
            raise ValueError("A price move would exhaust unlevered strategy equity.")
        equity *= gap_factor
        if trade_factor is not None:
            trade_factor *= gap_factor

        signal_history = [*history, *requested[:index]]
        desired = signal(signal_history) if signal_history else 0
        if desired not in (-1, 0, 1):
            raise ValueError("Signal must return -1, 0, or 1.")
        turnover = abs(desired - position)
        turnover_events += turnover
        if turnover:
            cost_factor = 1 - cost_fraction * turnover
            if cost_factor <= 0:
                raise ValueError("Turnover costs must be less than 100% of equity per fill.")
            equity *= cost_factor
            if position:
                trade_factor *= 1 - cost_fraction * abs(position)
                closed_trade_returns.append(trade_factor - 1)
                trade_factor = None
            if desired:
                trades += 1
                trade_factor = 1 - cost_fraction * abs(desired)
            position = desired

        intraday_return = close / opening - 1
        if not math.isfinite(intraday_return):
            raise ValueError("Price data produced a non-finite intraday return.")
        intraday_factor = 1 + position * intraday_return
        if intraday_factor <= 0:
            raise ValueError("A price move would exhaust unlevered strategy equity.")
        equity *= intraday_factor
        if trade_factor is not None:
            trade_factor *= intraday_factor
        daily_returns.append(equity / equity_at_previous_close - 1)
        if not math.isfinite(equity):
            raise ValueError("Simulation produced a non-finite equity value.")

    if trade_factor is not None:
        closed_trade_returns.append(trade_factor - 1)
    if not daily_returns:
        raise ValueError("No in-range returns were generated.")
    if not all(math.isfinite(value) for value in daily_returns + closed_trade_returns):
        raise ValueError("Simulation produced non-finite returns.")

    periods = len(daily_returns)
    try:
        annualized_return = math.expm1(math.log(equity) * 252 / periods) if periods > 1 else None
        daily_volatility = stdev(daily_returns) if periods > 1 else None
        annualized_volatility = daily_volatility * math.sqrt(252) if daily_volatility is not None else None
        sharpe = (fmean(daily_returns) / daily_volatility * math.sqrt(252)
                  if daily_volatility is not None and daily_volatility > 0 else None)
    except (OverflowError, ValueError) as exc:
        raise ValueError("Simulation metrics are non-finite.") from exc
    buy_and_hold = float(requested[-1].close) / _open(requested[0]) - 1
    win_rate = (sum(value > 0 for value in closed_trade_returns) / len(closed_trade_returns)
                if closed_trade_returns else None)
    values = (equity, buy_and_hold, _max_drawdown(daily_returns),
              annualized_return if annualized_return is not None else 0.0,
              annualized_volatility if annualized_volatility is not None else 0.0,
              sharpe if sharpe is not None else 0.0)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Simulation metrics are non-finite.")
    return SimulationResult(
        ticker=ticker, start=start, end=end, strategy=strategy, cost_bps=cost_bps,
        observations=periods, trades=trades, turnover_events=turnover_events,
        win_rate=round(win_rate, 4) if win_rate is not None else None,
        total_return_pct=round((equity - 1) * 100, 3),
        annualized_return_pct=round(annualized_return * 100, 3) if annualized_return is not None else None,
        annualized_volatility_pct=round(annualized_volatility * 100, 3) if annualized_volatility is not None else None,
        sharpe=round(sharpe, 3) if sharpe is not None else None,
        max_drawdown_pct=round(_max_drawdown(daily_returns) * 100, 3),
        buy_and_hold_return_pct=round(buy_and_hold * 100, 3),
        warnings=[
            "Signals use completed closes and fill at the following bar open; requested bars without opens are rejected.",
            "Returns include overnight gaps, 100% unlevered notional exposure, and simplified turnover costs; financing is excluded. Prices may be dividend-adjusted.",
            "Open and close prices are assumed to share an adjustment basis; positions are marked at end without forced liquidation.",
            "Volatility and Sharpe use sample standard deviation; Sharpe assumes a zero risk-free rate. Drawdown uses daily closes and cannot capture intraday lows.",
            "Results are historical research, not forecasts.",
        ],
    )


def _max_drawdown(returns: Sequence[float]) -> float:
    equity = peak = 1.0
    drawdown = 0.0
    for value in returns:
        equity *= 1 + value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1)
    return drawdown


def backtest_trend(bars: Sequence[object], start: str, end: str, fast_window: int = 20,
                   slow_window: int = 50, cost_bps: float = 10.0, ticker: str = "") -> SimulationResult:
    if fast_window < 2 or slow_window <= fast_window:
        raise ValueError("slow_window must be greater than fast_window, and fast_window at least 2.")

    def trend(history: Sequence[object]) -> int:
        closes = [float(bar.close) for bar in history]
        if len(closes) < slow_window + 1:
            return 0
        fast = fmean(closes[-fast_window:])
        slow = fmean(closes[-slow_window:])
        price = closes[-1]
        momentum = price / closes[-fast_window] - 1
        return (1 if price > fast > slow and momentum > 0
                else -1 if price < fast < slow and momentum < 0 else 0)

    return simulate(ticker, bars, start, end, f"trend_{fast_window}_{slow_window}", trend, cost_bps)


def backtest_strategy(bars: Sequence[object], start: str, end: str, strategy: str,
                      signal: Signal, cost_bps: float = 10.0, ticker: str = "") -> SimulationResult:
    return simulate(ticker, bars, start, end, strategy, signal, cost_bps)
