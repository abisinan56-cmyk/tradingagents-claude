"""Deterministic technical signals, risk templates, and reproducible strategy scoring.

This module is deliberately independent of the LLM pipeline. It never sends orders;
its outputs are research artefacts based only on completed daily price bars.
"""
from __future__ import annotations

import html
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import fmean, pstdev
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import HOME
from .markets import classify


@dataclass(frozen=True)
class PriceBar:
    day: str
    close: float
    open: float | None = None
    high: float | None = None
    low: float | None = None


@dataclass
class TradePlan:
    ticker: str
    as_of: str
    source_rating: str | None
    action: str
    confidence: str
    entry_reference: float
    stop_reference: float | None
    target_reference: float | None
    risk_per_unit_pct: float | None
    model_max_notional_pct: float
    holding_window: str
    technical_signal: str
    rationale: list[str]
    warnings: list[str] = field(default_factory=list)


@dataclass
class StrategyBacktest:
    ticker: str
    start: str
    end: str
    fast_window: int
    slow_window: int
    cost_bps: float
    observations: int
    trades: int
    win_rate: float | None
    total_return_pct: float
    annualized_return_pct: float | None
    annualized_volatility_pct: float | None
    sharpe: float | None
    max_drawdown_pct: float
    buy_and_hold_return_pct: float
    warnings: list[str] = field(default_factory=list)


def parse_yahoo_chart(payload: dict) -> list[PriceBar]:
    """Parse a Yahoo chart response into sorted completed adjusted-close bars."""
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        raise ValueError("Yahoo returned no daily price history.")
    chart = result[0]
    stamps = chart.get("timestamp") or []
    indicators = chart.get("indicators") or {}
    quote = (indicators.get("quote") or [{}])[0]
    closes = ((indicators.get("adjclose") or [{}])[0].get("adjclose") or quote.get("close") or [])
    opens, highs, lows = quote.get("open") or [], quote.get("high") or [], quote.get("low") or []
    bars = [PriceBar(datetime.fromtimestamp(ts, timezone.utc).date().isoformat(), float(close),
                     float(opens[i]) if i < len(opens) and opens[i] is not None else float(close),
                     float(highs[i]) if i < len(highs) and highs[i] is not None else float(close),
                     float(lows[i]) if i < len(lows) and lows[i] is not None else float(close))
            for i, (ts, close) in enumerate(zip(stamps, closes)) if close is not None and float(close) > 0]
    if not bars:
        raise ValueError("Yahoo returned no usable closing prices.")
    return bars


def fetch_daily_history(ticker: str, start: str, end: str) -> list[PriceBar]:
    """Fetch adjusted daily closes from Yahoo, retaining enough warm-up history."""
    symbol = classify(ticker).symbol
    start_day = date.fromisoformat(start) - timedelta(days=400)
    end_day = date.fromisoformat(end) + timedelta(days=1)
    params = urlencode({"period1": int(datetime.combine(start_day, datetime.min.time(), timezone.utc).timestamp()),
                        "period2": int(datetime.combine(end_day, datetime.min.time(), timezone.utc).timestamp()),
                        "interval": "1d", "events": "history"})
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{params}"
    try:
        with urlopen(Request(url, headers={"User-Agent": "ta-claude/0.1"}), timeout=15) as response:
            return parse_yahoo_chart(json.load(response))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Could not fetch Yahoo daily history for {symbol}: {exc}") from exc


def _mean(values: list[float]) -> float:
    return fmean(values) if values else 0.0


def _signal(closes: list[float], fast_window: int = 20, slow_window: int = 50) -> tuple[str, float, float, float]:
    if fast_window < 2 or slow_window <= fast_window:
        raise ValueError("slow window must be greater than fast window, and fast window must be at least 2.")
    if len(closes) < slow_window + 1:
        raise ValueError(f"Need at least {slow_window + 1} completed daily bars for this model.")
    price = closes[-1]
    fast = _mean(closes[-fast_window:])
    slow = _mean(closes[-slow_window:])
    momentum = price / closes[-fast_window] - 1
    if price > fast > slow and momentum > 0:
        return "long", fast, slow, momentum
    if price < fast < slow and momentum < 0:
        return "short", fast, slow, momentum
    return "flat", fast, slow, momentum


def _daily_volatility(closes: list[float]) -> float:
    returns = [b / a - 1 for a, b in zip(closes[-21:-1], closes[-20:]) if a > 0]
    return pstdev(returns) if len(returns) > 1 else 0.01


def build_trade_plan(ticker: str, bars: list[PriceBar], source_rating: str | None = None) -> TradePlan:
    """Build a transparent model plan from a rating label and completed price bars."""
    market = classify(ticker)
    closes = [bar.close for bar in bars]
    action, fast, slow, momentum = _signal(closes)
    rating_action = {"Buy": "long", "Overweight": "long", "Sell": "short", "Underweight": "short",
                     "Hold": "flat", "REVIEW": "flat"}.get(source_rating or "", None)
    warnings = list(market.warnings)
    if rating_action and rating_action != action:
        warnings.append("The LLM rating and deterministic trend model disagree; model confidence is reduced.")
    if source_rating in {"Hold", "REVIEW"}:
        action = "flat"
    volatility = _daily_volatility(closes)
    stop_pct = min(0.15, max(0.02, 2 * volatility)) if action != "flat" else None
    price = closes[-1]
    stop = target = None
    if action == "long":
        stop, target = price * (1 - stop_pct), price * (1 + 2 * stop_pct)
    elif action == "short":
        stop, target = price * (1 + stop_pct), price * (1 - 2 * stop_pct)
    confidence = "high" if rating_action == action and action != "flat" else "medium" if action != "flat" else "low"
    cap = 0.0 if action == "flat" else min(0.20, 0.01 / stop_pct)
    rationale = [f"Close {price:.4g}; 20-day average {fast:.4g}; 50-day average {slow:.4g}.",
                 f"20-day momentum is {momentum:+.2%}; daily volatility estimate is {volatility:.2%}."]
    if source_rating:
        rationale.append(f"Research rating input: {source_rating}.")
    return TradePlan(market.symbol, bars[-1].day, source_rating, action, confidence, round(price, 6),
                     round(stop, 6) if stop else None, round(target, 6) if target else None,
                     round(stop_pct * 100, 3) if stop_pct else None, round(cap * 100, 2), "20 trading days",
                     "20/50-day trend with 20-day momentum", rationale, warnings)


def backtest_trend(ticker: str, bars: list[PriceBar], start: str, end: str, fast_window: int = 20,
                    slow_window: int = 50, cost_bps: float = 10.0) -> StrategyBacktest:
    """Backtest a close-to-close, next-bar 20/50 trend strategy without future data."""
    if cost_bps < 0:
        raise ValueError("cost-bps must not be negative.")
    requested = [bar for bar in bars if start <= bar.day <= end]
    if len(requested) < 2:
        raise ValueError("The requested range needs at least two trading days.")
    equity = peak = 1.0
    max_drawdown = 0.0
    returns: list[float] = []
    trade_returns: list[float] = []
    position = 0
    entry_equity: float | None = None
    trades = 0
    for i in range(slow_window, len(bars) - 1):
        bar, next_bar = bars[i], bars[i + 1]
        if not (start <= bar.day <= end):
            continue
        signal, *_ = _signal([x.close for x in bars[:i + 1]], fast_window, slow_window)
        desired = {"long": 1, "short": -1, "flat": 0}[signal]
        turnover = abs(desired - position)
        if turnover:
            if position and entry_equity is not None:
                trade_returns.append(equity / entry_equity - 1)
            if desired:
                entry_equity = equity
            else:
                entry_equity = None
            trades += turnover
        cost = turnover * cost_bps / 10_000
        gross = desired * (next_bar.close / bar.close - 1)
        net = gross - cost
        equity *= 1 + net
        returns.append(net)
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1)
        position = desired
    if position and entry_equity is not None:
        trade_returns.append(equity / entry_equity - 1)
    if not returns:
        raise ValueError("Insufficient warmed-up bars inside the requested range.")
    ann_return = (equity ** (252 / len(returns)) - 1) if len(returns) >= 2 else None
    ann_vol = pstdev(returns) * math.sqrt(252) if len(returns) > 1 else None
    sharpe = ann_return / ann_vol if ann_return is not None and ann_vol else None
    first, last = requested[0].close, requested[-1].close
    return StrategyBacktest(classify(ticker).symbol, start, end, fast_window, slow_window, cost_bps, len(returns),
                            trades, round(sum(x > 0 for x in trade_returns) / len(trade_returns), 4) if trade_returns else None,
                            round((equity - 1) * 100, 3), round(ann_return * 100, 3) if ann_return is not None else None,
                            round(ann_vol * 100, 3) if ann_vol is not None else None,
                            round(sharpe, 3) if sharpe is not None else None, round(max_drawdown * 100, 3),
                            round((last / first - 1) * 100, 3),
                            ["Signals use completed closes and apply to the following close-to-close return.",
                             "Results are a deterministic research simulation, not evidence of future performance."])


def write_trade_plan_dashboard(plan: TradePlan) -> str:
    """Save a portable, dependency-free HTML research dashboard for a trade plan."""
    path = HOME / "trade-plans" / f"{plan.ticker.replace('/', '_')}_{plan.as_of}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = "".join(f"<tr><th>{html.escape(key.replace('_', ' ').title())}</th><td>{html.escape(str(value))}</td></tr>"
                   for key, value in asdict(plan).items() if key not in {"rationale", "warnings"})
    notes = "".join(f"<li>{html.escape(note)}</li>" for note in plan.rationale + plan.warnings)
    path.write_text(f"<!doctype html><title>{html.escape(plan.ticker)} research plan</title>"
                    f"<style>body{{font:16px system-ui;max-width:760px;margin:3rem auto}}th{{text-align:left;padding-right:2rem}}td,th{{padding:.35rem}}li{{margin:.4rem}}</style>"
                    f"<h1>{html.escape(plan.ticker)} model research plan</h1><p>Research only. Not financial, investment or trading advice.</p>"
                    f"<table>{rows}</table><h2>Model notes</h2><ul>{notes}</ul>", encoding="utf-8")
    return str(path)

MAJOR_FX_PAIRS = ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD")


@dataclass
class FXScan:
    as_of: str
    pairs_scanned: list[str]
    candidates: list[dict]
    unavailable: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=lambda: [
        "Ranks are deterministic technical research candidates, not trade recommendations.",
        "Daily Yahoo bars can be delayed and do not include executable bid/ask spreads or upcoming-event surprises.",
    ])


def scan_fx(pairs: list[str] | tuple[str, ...] = MAJOR_FX_PAIRS) -> FXScan:
    """Rank liquid major FX pairs by trend strength using the same transparent model."""
    candidates: list[dict] = []
    unavailable: dict[str, str] = {}
    today = date.today()
    for pair in pairs:
        try:
            bars = fetch_daily_history(pair, (today - timedelta(days=730)).isoformat(), today.isoformat())
            plan = build_trade_plan(pair, bars)
            closes = [bar.close for bar in bars]
            _, _, _, momentum = _signal(closes)
            volatility = _daily_volatility(closes)
            strength = abs(momentum) / volatility if volatility else 0.0
            candidates.append({**asdict(plan), "trend_strength": round(strength, 3)})
        except ValueError as exc:
            unavailable[pair] = str(exc)
    candidates.sort(key=lambda item: (item["action"] == "flat", -item["trend_strength"], item["ticker"]))
    for rank, candidate in enumerate(candidates, start=1):
        candidate["rank"] = rank
    if not candidates:
        raise ValueError("No FX pair histories were available for the scan.")
    return FXScan(max(item["as_of"] for item in candidates), [classify(pair).symbol for pair in pairs],
                  candidates, unavailable)

def _ema(values: list[float], period: int) -> float:
    if len(values) < period:
        raise ValueError(f"Need at least {period} bars for this indicator.")
    multiplier = 2 / (period + 1)
    value = _mean(values[:period])
    for price in values[period:]:
        value = price * multiplier + value * (1 - multiplier)
    return value


def _rsi(closes: list[float], period: int = 14) -> float:
    changes = [b - a for a, b in zip(closes[-period - 1:-1], closes[-period:])]
    gains = _mean([max(change, 0) for change in changes])
    losses = _mean([max(-change, 0) for change in changes])
    return 100.0 if losses == 0 else round(100 - (100 / (1 + gains / losses)), 2)


def _ohlc(bar: PriceBar) -> tuple[float, float, float, float]:
    return bar.open or bar.close, bar.high or bar.close, bar.low or bar.close, bar.close


def technical_analysis(bars: list[PriceBar]) -> dict:
    """Calculate transparent completed-bar trend, momentum, volatility and candle evidence."""
    if len(bars) < 51:
        raise ValueError("Need at least 51 completed bars for technical analysis.")
    closes = [bar.close for bar in bars]
    last, previous = bars[-1], bars[-2]
    op, high, low, close = _ohlc(last)
    prev_open, _, _, prev_close = _ohlc(previous)
    body, range_ = abs(close - op), max(high - low, 1e-12)
    upper_wick, lower_wick = high - max(op, close), min(op, close) - low
    candle = "bullish" if close > op else "bearish" if close < op else "doji"
    patterns: list[str] = []
    if body / range_ <= 0.1:
        patterns.append("doji (indecision)")
    if lower_wick >= 2 * max(body, 1e-12) and close >= op:
        patterns.append("bullish pin bar")
    if upper_wick >= 2 * max(body, 1e-12) and close <= op:
        patterns.append("bearish pin bar")
    if close > op and prev_close < prev_open and close >= prev_open and op <= prev_close:
        patterns.append("bullish engulfing")
    if close < op and prev_close > prev_open and close <= prev_open and op >= prev_close:
        patterns.append("bearish engulfing")
    prev_high, prev_low = _ohlc(previous)[1:3]
    if high <= prev_high and low >= prev_low:
        patterns.append("inside bar")
    true_ranges = [max((bar.high or bar.close) - (bar.low or bar.close),
                       abs((bar.high or bar.close) - prior.close), abs((bar.low or bar.close) - prior.close))
                   for prior, bar in zip(bars[-15:-1], bars[-14:])]
    atr = _mean(true_ranges)
    sma20, sma50 = _mean(closes[-20:]), _mean(closes[-50:])
    std20 = pstdev(closes[-20:])
    ema12, ema26 = _ema(closes, 12), _ema(closes, 26)
    macd = ema12 - ema26
    macd_series = [_ema(closes[:i], 12) - _ema(closes[:i], 26) for i in range(35, len(closes) + 1)]
    signal = _ema(macd_series, 9)
    support, resistance = min((bar.low or bar.close) for bar in bars[-20:]), max((bar.high or bar.close) for bar in bars[-20:])
    return {"timeframe": "completed daily bars", "last_candle": {"day": last.day, "open": round(op, 6), "high": round(high, 6),
            "low": round(low, 6), "close": round(close, 6), "direction": candle, "body_pct_of_range": round(body / range_ * 100, 2),
            "upper_wick": round(upper_wick, 6), "lower_wick": round(lower_wick, 6), "patterns": patterns or ["no named single-candle pattern"]},
            "trend": {"sma_20": round(sma20, 6), "sma_50": round(sma50, 6), "price_vs_sma20_pct": round((close / sma20 - 1) * 100, 3),
                      "price_vs_sma50_pct": round((close / sma50 - 1) * 100, 3)},
            "momentum": {"rsi_14": _rsi(closes), "macd": round(macd, 6), "macd_signal": round(signal, 6),
                         "macd_histogram": round(macd - signal, 6)},
            "volatility": {"atr_14": round(atr, 6), "atr_14_pct": round(atr / close * 100, 3),
                           "bollinger_lower": round(sma20 - 2 * std20, 6), "bollinger_upper": round(sma20 + 2 * std20, 6)},
            "levels": {"support_20": round(support, 6), "resistance_20": round(resistance, 6)}}


@dataclass
class FXDecisionBrief:
    """A structured, non-personalised FX research brief."""
    pair: str
    as_of: str
    setup: dict
    technical_analysis: dict
    market_regime: str
    bullish_scenario: dict
    bearish_scenario: dict
    no_trade_conditions: list[str]
    event_risk_checklist: list[str]
    risk_profiles: dict[str, dict]
    currency_exposure: dict[str, int]
    portfolio_overlap: dict[str, int]
    warnings: list[str] = field(default_factory=list)


def _pair_currencies(symbol: str) -> tuple[str, str]:
    pair = symbol.upper().replace("=X", "")
    if len(pair) != 6 or not pair.isalpha():
        raise ValueError(f"{symbol} is not a six-letter FX pair.")
    return pair[:3], pair[3:]


def currency_exposure(symbol: str, action: str, multiplier: int = 1) -> dict[str, int]:
    """Represent long/short pair exposure in currency units, not portfolio value."""
    base, quote = _pair_currencies(symbol)
    direction = {"long": 1, "short": -1, "flat": 0}.get(action)
    if direction is None:
        raise ValueError(f"Unknown FX action: {action}")
    return {base: direction * multiplier, quote: -direction * multiplier} if direction else {}


def portfolio_currency_overlap(path: str | None) -> dict[str, int]:
    """Summarise declared FX positions only; unknown instruments are intentionally ignored."""
    if not path:
        return {}
    try:
        positions = json.loads(Path(path).read_text(encoding="utf-8")).get("positions", [])
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read portfolio JSON: {exc}") from exc
    exposure: dict[str, int] = {}
    for position in positions:
        ticker = str(position.get("ticker", ""))
        try:
            base, quote = _pair_currencies(ticker)
        except ValueError:
            continue
        quantity = float(position.get("quantity", 0))
        if quantity == 0:
            continue
        sign = 1 if quantity > 0 else -1
        exposure[base] = exposure.get(base, 0) + sign
        exposure[quote] = exposure.get(quote, 0) - sign
    return {currency: unit for currency, unit in sorted(exposure.items()) if unit}


def build_fx_decision_brief(ticker: str, bars: list[PriceBar], portfolio: str | None = None,
                            source_rating: str | None = None) -> FXDecisionBrief:
    """Frame technical evidence and invalidation conditions without making a personal recommendation."""
    plan = build_trade_plan(ticker, bars, source_rating)
    base, quote = _pair_currencies(plan.ticker)
    trend_description = (f"{plan.action.title()} trend regime: the completed close is aligned with the 20/50-day averages "
                         "and 20-day momentum." if plan.action != "flat" else
                         "Mixed/flat trend regime: the model has no directional confirmation.")
    bullish = {"condition": f"{base} strengthens versus {quote}; price remains above the entry reference and confirms trend.",
               "reference_target": plan.target_reference if plan.action == "long" else plan.stop_reference,
               "invalidation": plan.stop_reference if plan.action == "long" else plan.target_reference}
    bearish = {"condition": f"{quote} strengthens versus {base}; price breaks the opposite trend/risk reference.",
               "reference_target": plan.target_reference if plan.action == "short" else plan.stop_reference,
               "invalidation": plan.stop_reference if plan.action == "short" else plan.target_reference}
    no_trade = ["The signal is flat, or the completed daily bar has not confirmed the trend.",
                "Price is near the model stop/reference, leaving poor room for the stated risk distance.",
                "A high-impact central-bank, inflation, jobs, or policy event is imminent and its result is unknown.",
                "Available price data is stale, illiquid, or materially differs from the executable quote/spread."]
    risk_profiles = {
        "conservative": {"assumption": "No new exposure until trend confirmation after a high-impact event; uses the model risk reference only as an invalidation check."},
        "balanced": {"assumption": "Requires a confirmed daily trend and predefined loss limit; model maximum notional is a ceiling, not a recommendation.",
                     "model_ceiling_pct": plan.model_max_notional_pct},
        "aggressive": {"assumption": "Higher volatility tolerance does not change the invalidation reference; leverage, spreads, and gaps can exceed modeled loss."},
    }
    warnings = list(plan.warnings) + [
        "No live economic-calendar feed is connected: verify scheduled central-bank, inflation, employment, and policy events independently.",
        "No bid/ask, liquidity, financing, tax, leverage, or personal-suitability data is used.",
        "This is general market research, not personalised financial advice or an instruction to trade.",
    ]
    return FXDecisionBrief(plan.ticker, plan.as_of, asdict(plan), technical_analysis(bars), trend_description, bullish, bearish, no_trade,
                           [f"Check {base} and {quote} central-bank decisions and speeches.",
                            f"Check {base} and {quote} inflation, employment, GDP, and purchasing-manager releases.",
                            "Check policy/geopolitical headlines and whether market liquidity is reduced by a holiday/session handover."],
                           risk_profiles, currency_exposure(plan.ticker, plan.action), portfolio_currency_overlap(portfolio), warnings)

STRATEGIES = ("trend", "mean_reversion", "breakout", "rsi_momentum")


@dataclass
class StrategySuite:
    ticker: str
    start: str
    end: str
    cost_bps: float
    results: list[dict]
    warnings: list[str] = field(default_factory=lambda: [
        "Each strategy uses completed daily bars and applies to the following close-to-close return.",
        "This comparison is in-sample historical research; it does not select a future winner or establish an edge.",
        "Costs are a simplified turnover estimate and exclude bid/ask spread, slippage, financing, and gaps.",
    ])


def _strategy_direction(name: str, history: list[PriceBar]) -> int:
    closes = [bar.close for bar in history]
    if name == "trend":
        return {"long": 1, "short": -1, "flat": 0}[_signal(closes)[0]]
    if name == "mean_reversion":
        sma, band = _mean(closes[-20:]), 2 * pstdev(closes[-20:])
        rsi = _rsi(closes)
        return 1 if closes[-1] <= sma - band and rsi < 35 else -1 if closes[-1] >= sma + band and rsi > 65 else 0
    if name == "breakout":
        prior = history[-21:-1]
        high = max((bar.high or bar.close) for bar in prior)
        low = min((bar.low or bar.close) for bar in prior)
        return 1 if closes[-1] > high else -1 if closes[-1] < low else 0
    if name == "rsi_momentum":
        rsi = _rsi(closes)
        return 1 if rsi >= 55 else -1 if rsi <= 45 else 0
    raise ValueError(f"Unknown strategy {name!r}; choose from {', '.join(STRATEGIES)}.")


def backtest_strategy(ticker: str, bars: list[PriceBar], start: str, end: str, strategy: str,
                      cost_bps: float = 10.0) -> dict:
    """Evaluate one fixed signal family with identical execution/cost assumptions."""
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy {strategy!r}; choose from {', '.join(STRATEGIES)}.")
    if cost_bps < 0:
        raise ValueError("cost-bps must not be negative.")
    requested = [bar for bar in bars if start <= bar.day <= end]
    if len(requested) < 2:
        raise ValueError("The requested range needs at least two trading days.")
    equity = peak = 1.0
    returns: list[float] = []
    position = 0
    turnover_events = 0
    max_drawdown = 0.0
    for i in range(50, len(bars) - 1):
        bar, next_bar = bars[i], bars[i + 1]
        if not (start <= bar.day <= end):
            continue
        desired = _strategy_direction(strategy, bars[:i + 1])
        turnover = abs(desired - position)
        turnover_events += turnover
        net = desired * (next_bar.close / bar.close - 1) - turnover * cost_bps / 10_000
        equity *= 1 + net
        returns.append(net)
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1)
        position = desired
    if not returns:
        raise ValueError("Insufficient warmed-up bars inside the requested range.")
    annualized = equity ** (252 / len(returns)) - 1 if len(returns) > 1 else None
    volatility = pstdev(returns) * math.sqrt(252) if len(returns) > 1 else None
    return {"strategy": strategy, "observations": len(returns), "turnover_events": turnover_events,
            "total_return_pct": round((equity - 1) * 100, 3), "annualized_return_pct": round(annualized * 100, 3) if annualized is not None else None,
            "annualized_volatility_pct": round(volatility * 100, 3) if volatility is not None else None,
            "sharpe": round(annualized / volatility, 3) if annualized is not None and volatility else None,
            "max_drawdown_pct": round(max_drawdown * 100, 3), "buy_and_hold_return_pct": round((requested[-1].close / requested[0].close - 1) * 100, 3)}


def backtest_strategy_suite(ticker: str, bars: list[PriceBar], start: str, end: str,
                            cost_bps: float = 10.0) -> StrategySuite:
    """Compare four complementary, documented daily-bar signal families."""
    results = [backtest_strategy(ticker, bars, start, end, strategy, cost_bps) for strategy in STRATEGIES]
    return StrategySuite(classify(ticker).symbol, start, end, cost_bps, results)
