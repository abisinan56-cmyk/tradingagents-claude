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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


def parse_yahoo_chart(payload: dict, *, now: datetime | None = None) -> list[PriceBar]:
    """Parse consistently adjusted daily OHLC; omit bars less than 48 hours old.

    Yahoo timestamps mark the start of a daily bar, not its completion. The
    conservative 48-hour delay avoids relying on exchange-specific sessions.
    """
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        raise ValueError("Yahoo returned no daily price history.")
    chart = result[0]
    stamps = chart.get("timestamp") or []
    indicators = chart.get("indicators") or {}
    quote = (indicators.get("quote") or [{}])[0]
    raw_closes = quote.get("close") or []
    adjusted = (indicators.get("adjclose") or [{}])[0].get("adjclose") or []
    fields = [quote.get(name) or [] for name in ("open", "high", "low")]
    cutoff = (now or datetime.now(timezone.utc)).timestamp() - 48 * 3600
    try:
        exchange_zone = ZoneInfo(chart.get("meta", {}).get("exchangeTimezoneName") or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        exchange_zone = timezone.utc
    bars = []
    for i, ts in enumerate(stamps):
        if ts > cutoff or i >= len(raw_closes) or raw_closes[i] is None:
            continue
        raw = float(raw_closes[i])
        close = float(adjusted[i]) if i < len(adjusted) and adjusted[i] is not None else raw
        if not math.isfinite(raw) or not math.isfinite(close) or raw <= 0 or close <= 0:
            continue
        factor = close / raw
        ohl = []
        for values in fields:
            value = float(values[i]) * factor if i < len(values) and values[i] is not None else None
            ohl.append(value if value is not None and math.isfinite(value) and value > 0 else None)
        bars.append(PriceBar(datetime.fromtimestamp(ts, exchange_zone).date().isoformat(), close, *ohl))
    bars.sort(key=lambda bar: bar.day)
    if not bars:
        raise ValueError("Yahoo returned no usable completed daily bars.")
    if len({bar.day for bar in bars}) != len(bars):
        raise ValueError("Yahoo returned duplicate daily bars.")
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
    age_days = (datetime.now(timezone.utc).date() - date.fromisoformat(bars[-1].day)).days
    if age_days > 4:
        warnings.append(f"Latest daily bar is {age_days} calendar days old; verify market hours and data freshness.")
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
    """Use completed-close signals and next-open fills within the requested dates."""
    from .simulation import backtest_trend as simulate_trend
    result = simulate_trend(bars, start, end, fast_window, slow_window, cost_bps,
                            ticker=classify(ticker).symbol)
    return StrategyBacktest(result.ticker, start, end, fast_window, slow_window, cost_bps,
                            result.observations, result.trades, result.win_rate, result.total_return_pct,
                            result.annualized_return_pct, result.annualized_volatility_pct, result.sharpe,
                            result.max_drawdown_pct, result.buy_and_hold_return_pct, result.warnings)


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
            if classify(pair).name != "fx":
                raise ValueError(f"{pair} is not a recognised FX pair.")
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
    if losses == 0:
        return 50.0 if gains == 0 else 100.0
    return round(100 - (100 / (1 + gains / losses)), 2)


def _ohlc(bar: PriceBar) -> tuple[float, float, float, float]:
    return bar.open or bar.close, bar.high or bar.close, bar.low or bar.close, bar.close


def technical_analysis(bars: list[PriceBar]) -> dict:
    """Calculate transparent completed-bar trend, momentum, volatility and candle evidence."""
    if len(bars) < 51:
        raise ValueError("Need at least 51 completed bars for technical analysis.")
    closes = [bar.close for bar in bars]
    last, previous = bars[-1], bars[-2]
    if any(value is None for bar in bars[-20:] for value in (bar.open, bar.high, bar.low)):
        raise ValueError("OHLC data is incomplete; candle and volatility analysis unavailable.")
    op, high, low, close = _ohlc(last)
    prev_open, _, _, prev_close = _ohlc(previous)
    body, range_ = abs(close - op), max(high - low, 1e-12)
    upper_wick, lower_wick = high - max(op, close), min(op, close) - low
    candle = "bullish" if close > op else "bearish" if close < op else "doji"
    patterns: list[str] = []
    if body / range_ <= 0.1:
        patterns.append("doji (indecision)")
    if body > range_ * 0.1 and lower_wick >= 2 * body and upper_wick <= body and close > op:
        patterns.append("bullish pin bar")
    if body > range_ * 0.1 and upper_wick >= 2 * body and lower_wick <= body and close < op:
        patterns.append("bearish pin bar")
    if close > op and prev_close < prev_open and close >= prev_open and op <= prev_close:
        patterns.append("bullish engulfing")
    if close < op and prev_close > prev_open and close <= prev_open and op >= prev_close:
        patterns.append("bearish engulfing")
    prev_high, prev_low = _ohlc(previous)[1:3]
    if high < prev_high and low > prev_low:
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
    portfolio_overlap: dict
    warnings: list[str] = field(default_factory=list)


def _pair_currencies(symbol: str) -> tuple[str, str]:
    pair = symbol.upper().replace("=X", "")
    from .markets import CURRENCIES
    if (len(pair) != 6 or not pair.isalpha() or pair[:3] not in CURRENCIES
            or pair[3:] not in CURRENCIES or pair[:3] == pair[3:]):
        raise ValueError(f"{symbol} is not a supported FX pair.")
    return pair[:3], pair[3:]


def currency_exposure(symbol: str, action: str, multiplier: int = 1) -> dict[str, int]:
    """Represent long/short pair exposure in currency units, not portfolio value."""
    base, quote = _pair_currencies(symbol)
    direction = {"long": 1, "short": -1, "flat": 0}.get(action)
    if direction is None:
        raise ValueError(f"Unknown FX action: {action}")
    return {base: direction * multiplier, quote: -direction * multiplier} if direction else {}


def portfolio_currency_overlap(path: str | None) -> dict:
    """Return itemized cost-basis FX legs, not live or net portfolio exposure."""
    if not path:
        return {"positions": [], "assumptions": ["No portfolio was supplied."]}
    from .fx_exposure import portfolio_fx_exposure
    return portfolio_fx_exposure(path)


def build_fx_decision_brief(ticker: str, bars: list[PriceBar], portfolio: str | None = None,
                            source_rating: str | None = None) -> FXDecisionBrief:
    """Frame technical evidence and invalidation conditions without making a personal recommendation."""
    plan = build_trade_plan(ticker, bars, source_rating)
    base, quote = _pair_currencies(plan.ticker)
    technical_direction, *_ = _signal([bar.close for bar in bars])
    trend_description = (f"{technical_direction.title()} trend regime: the completed close is aligned with the 20/50-day averages "
                         "and 20-day momentum." if technical_direction != "flat" else
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
        "Signals use completed closes and fill at the following bar open, with overnight gaps accounted for.",
        "This comparison is in-sample historical research; it does not select a future winner or establish an edge.",
        "Costs are a simplified turnover estimate; bid/ask spread, slippage and financing are excluded.",
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
        if any(bar.high is None or bar.low is None for bar in prior):
            raise ValueError("Breakout strategy requires historical high and low prices.")
        high = max(bar.high for bar in prior)
        low = min(bar.low for bar in prior)
        return 1 if closes[-1] > high else -1 if closes[-1] < low else 0
    if name == "rsi_momentum":
        rsi = _rsi(closes)
        return 1 if rsi >= 55 else -1 if rsi <= 45 else 0
    raise ValueError(f"Unknown strategy {name!r}; choose from {', '.join(STRATEGIES)}.")


def backtest_strategy(ticker: str, bars: list[PriceBar], start: str, end: str, strategy: str,
                      cost_bps: float = 10.0) -> dict:
    """Evaluate one fixed signal family with next-open fills and identical costs."""
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy {strategy!r}; choose from {', '.join(STRATEGIES)}.")
    from .simulation import backtest_strategy as simulate_strategy

    def signal(history):
        return _strategy_direction(strategy, history) if len(history) >= 51 else 0

    result = simulate_strategy(bars, start, end, strategy, signal, cost_bps,
                               ticker=classify(ticker).symbol)
    return asdict(result)


def backtest_strategy_suite(ticker: str, bars: list[PriceBar], start: str, end: str,
                            cost_bps: float = 10.0) -> StrategySuite:
    """Compare four complementary, documented daily-bar signal families."""
    results = [backtest_strategy(ticker, bars, start, end, strategy, cost_bps) for strategy in STRATEGIES]
    return StrategySuite(classify(ticker).symbol, start, end, cost_bps, results)
