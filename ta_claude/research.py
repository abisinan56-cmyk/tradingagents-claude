"""Keyless research pack: everything the TradingAgents roles need, with no API key.

The CLI gathers deterministic inputs from Yahoo (no key, no account): prices, the technical
snapshot, the plan, the FX brief and dated headlines. The Claude session running the skill
(Claude desktop / Claude Code, on the user's own subscription) then enriches it with its own
connectors (Firecrawl, Twelve Data, Claude in Chrome, web search) and writes the analyst,
researcher, trader, risk and portfolio-manager sections. No fetch here needs a key, and
each one fails open: a missing source becomes a warning, never an error.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

from .markets import classify

CONNECTOR_STEPS = [
    "Full articles: if the Firecrawl connector is connected, scrape the 2-3 most relevant URLs in `news` "
    "(main content only) and summarise each in one dated line with its source; otherwise use web fetch or skip.",
    "Calendar: for the currencies in `calendar_currencies`, find this week's high-impact events (central-bank decisions, "
    "CPI, jobs, GDP) with the Firecrawl connector on forexfactory.com/calendar, or Claude in Chrome / web search. "
    "Quote times in UTC; never invent an event or a forecast.",
    "Live price: if the Twelve Data connector is connected, one get_quote call for the latest price; say which source each number came from.",
]

ANALYSIS_STEPS = [
    "Write the analysis yourself in TradingAgents order; each role 1-3 lines citing a number or source from this pack or a connector.",
    "Market/technical analyst: use technical_snapshot and plan (20/50 regime, candle, RSI-14, MACD, ATR-14, Bollinger, support/resistance).",
    "News/macro analyst: only dated items, each with its source; say so if there are none.",
    "Fundamentals analyst: stocks only, and only from a search or scrape; FX and crypto have none.",
    "Sentiment analyst: skip and say 'no social data in keyless mode'.",
    "Bull vs bear: the strongest case each way. Research manager: which side wins and why.",
    "Trader: invalidation and trigger levels; stop 1.5x ATR-14 beyond the level (0.3%-15% of price), target 2x the stop; "
    "a flat regime means no entry or stop. If a high-impact event is within 24 hours, say no new exposure before it.",
    "Risk team: one line each, aggressive, conservative and neutral. Portfolio manager: Rating: Buy / Overweight / Hold / Underweight / Sell.",
    "Label the result 'Keyless TradingAgents (single model + ta-claude data)' and end with: research only, not financial advice.",
]


def fetch_news(symbol: str, as_of: str, limit: int = 8) -> list[dict]:
    """Dated Yahoo headlines published on or before ``as_of``; keyless."""
    import yfinance as yf

    items = []
    for raw in yf.Ticker(symbol).news or []:
        content = raw.get("content", raw)
        published = (content.get("pubDate") or "")[:10]
        title = (content.get("title") or "").strip()
        if not published or not title or published > as_of:
            continue
        provider = content.get("provider") or {}
        link = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
        items.append({"date": published, "title": title,
                      "source": provider.get("displayName") if isinstance(provider, dict) else None,
                      "url": link.get("url") if isinstance(link, dict) else None})
    items.sort(key=lambda item: item["date"], reverse=True)
    return items[:limit]


def calendar_currencies(ticker: str) -> list[str]:
    market = classify(ticker)
    if market.name == "fx":
        pair = market.symbol.upper().replace("=X", "")
        return [pair[:3], pair[3:]]
    if market.name in {"us", "crypto"}:
        return ["USD"]
    return []


def build_research_pack(ticker: str, as_of: str | None = None) -> dict:
    """Assemble the keyless pack; raises ValueError only when there is no price data at all."""
    from .model import build_fx_decision_brief, build_trade_plan, fetch_daily_history, technical_snapshot

    market = classify(ticker)
    if not market.analysts:
        raise ValueError(" ".join(market.warnings) or f"No data source for {market.symbol}.")
    as_of = as_of or date.today().isoformat()
    warnings = list(market.warnings)

    bars = fetch_daily_history(market.symbol, (date.fromisoformat(as_of) - timedelta(days=730)).isoformat(), as_of)
    plan = build_trade_plan(market.symbol, bars)
    warnings += [w for w in plan.warnings if w not in warnings]
    pack = {"mode": "keyless", "ticker": market.symbol, "market": market.name, "as_of": plan.as_of,
            "technical_snapshot": technical_snapshot(market.symbol, as_of), "plan": asdict(plan)}
    if market.name == "fx":
        brief = asdict(build_fx_decision_brief(market.symbol, bars))
        pack["fx_brief"] = {key: brief[key] for key in ("market_regime", "bullish_scenario", "bearish_scenario",
                                                         "no_trade_conditions", "currency_exposure")}
    try:
        pack["news"] = fetch_news(market.symbol, as_of)
        if not pack["news"]:
            warnings.append("No dated Yahoo headlines on or before the analysis date (Yahoo keeps recent news only).")
    except Exception as exc:  # network, schema or rate-limit: the pack still stands
        pack["news"] = []
        warnings.append(f"Yahoo news unavailable: {exc}")
    pack["calendar_currencies"] = calendar_currencies(market.symbol)
    pack["connector_steps"] = CONNECTOR_STEPS
    pack["analysis_steps"] = ANALYSIS_STEPS
    pack["warnings"] = warnings
    return pack
