"""Classify a ticker into a market and pick the pipeline that fits it."""
from __future__ import annotations

from dataclasses import dataclass, field

from tradingagents.dataflows.symbols import normalize_symbol

# Currencies hard-pegged to USD: a pair of two of these barely moves, so the
# agents have nothing to analyse and any "signal" is noise.
USD_PEGGED = {"USD", "AED", "SAR", "QAR", "OMR", "BHD", "HKD", "JOD"}


@dataclass
class Market:
    name: str            # us | uae | india | crypto | fx | other
    symbol: str          # Yahoo symbol after normalisation
    asset_type: str      # passed to TradingAgents: "stock" or "crypto"
    analysts: list[str]
    point_in_time_fundamentals: bool
    warnings: list[str] = field(default_factory=list)


CURRENCIES = USD_PEGGED | {"EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY", "CNH",
                           "INR", "KWD", "EGP", "PKR", "SGD", "ZAR", "TRY", "SEK", "NOK", "MXN"}


def classify(ticker: str) -> Market:
    sym = normalize_symbol(ticker.strip())
    up = sym.upper()
    # Upstream only knows the common ISO codes; give Gulf/other pairs Yahoo's =X too.
    if len(up) == 6 and up.isalpha() and up[:3] in CURRENCIES and up[3:] in CURRENCIES:
        sym = up = up + "=X"

    if up.endswith("=X"):
        pair = up[:-2]
        warns = []
        if len(pair) == 6 and pair[:3] in USD_PEGGED and pair[3:] in USD_PEGGED:
            warns.append(f"{pair} is a pegged pair; expect near-zero movement and meaningless signals.")
        warns.append("FX alpha is measured against the US Dollar Index; judge FX calls on raw return.")
        # The non-company ("asset") pipeline: no fundamentals or insider tools.
        return Market("fx", sym, "crypto", ["market", "news"], False, warns)

    if up.endswith("-USD") or up.endswith("-USDT"):
        return Market("crypto", sym, "crypto", ["market", "social", "news"], False)

    if up.endswith(".AD") or up.endswith(".ADX"):
        return Market("uae-adx", sym, "stock", [], False, [
            "Abu Dhabi (ADX) stocks are not on Yahoo Finance, so the agents have no data for them. "
            "Use live mode on an ADX page for a screen-based read instead.",
        ])

    if up.endswith(".AE"):
        return Market("uae", sym, "stock", ["market", "news", "fundamentals"], False, [
            "UAE fundamentals come from Yahoo and are withheld on past-dated runs; "
            "backtests rely on price and news only.",
            "Alpha is against the iShares MSCI UAE ETF (UAE) as a proxy for the local index.",
        ])

    if up.endswith(".NS") or up.endswith(".BO"):
        return Market("india", sym, "stock", ["market", "news", "fundamentals"], False, [
            "Indian fundamentals are withheld on past-dated runs (no point-in-time source).",
        ])

    if "." not in up or up.endswith(".B") or up.endswith(".A"):
        return Market("us", sym, "stock", ["market", "social", "news", "fundamentals"], True)

    return Market("other", sym, "stock", ["market", "news", "fundamentals"], False,
                  ["Market not in this project's presets; using generic stock settings."])


def backtest_analysts(market: Market) -> list[str]:
    """Analysts whose inputs are point-in-time safe for a past-dated run.

    Social feeds (StockTwits/Reddit) are fetched as of now, not as of the run date,
    so they leak the future into a backtest and are always dropped.
    """
    return [a for a in market.analysts if a != "social"]
