"""Cost-basis currency legs for declared FX positions; not current valuations."""
from __future__ import annotations

import json
import math
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

from .markets import CURRENCIES


_PRICE_LABEL = (
    "supplied average_price; quote currency per base-currency unit "
    "(historical cost basis, not current market price)"
)
_ASSUMPTIONS = [
    "quantity is signed units of the pair's base currency (positive long, negative short).",
    "average_price is quote-currency units per one base-currency unit.",
    "The quote leg uses quantity × supplied average_price; it is a cost-basis amount, not a current mark.",
    "Positions are returned separately and never netted or converted across currencies.",
    "Only currency pairs supported by this repository are recognized; other portfolio holdings are ignored.",
    "Fees, financing, leverage, contract multipliers, cash balances, and current FX rates are excluded.",
]


def _fx_pair(ticker: Any) -> tuple[str, str, str]:
    if not isinstance(ticker, str):
        raise ValueError("FX ticker must be a string containing a supported currency pair.")
    symbol = ticker.strip().upper()
    if symbol.endswith("=X"):
        symbol = symbol[:-2]
    if len(symbol) != 6 or not symbol.isalpha():
        raise ValueError(f"{ticker!r} is not a supported six-letter FX pair.")
    base, quote = symbol[:3], symbol[3:]
    if base not in CURRENCIES or quote not in CURRENCIES or base == quote:
        raise ValueError(f"{ticker!r} is not a supported FX pair.")
    return symbol, base, quote


def _finite_number(value: Any, label: str, *, positive: bool = False) -> int | float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or isinstance(value, float) and not math.isfinite(value)):
        raise ValueError(f"{label} must be a finite JSON number.")
    if positive and value <= 0:
        raise ValueError(f"{label} must be greater than zero.")
    return value


def fx_position_exposure(position: Mapping[str, Any]) -> dict[str, Any]:
    """Return the two signed currency legs for one FX position.

    The existing portfolio convention is used: ``quantity`` is base-currency
    units and ``average_price`` is quote currency per base-currency unit.
    """
    if not isinstance(position, Mapping):
        raise ValueError("Each FX position must be a JSON object.")
    pair, base, quote = _fx_pair(position.get("ticker"))
    quantity = _finite_number(position.get("quantity"), "quantity")
    price = _finite_number(position.get("average_price"), "average_price", positive=True)
    if quantity == 0:
        raise ValueError("quantity must not be zero for an FX position.")
    quote_amount = Decimal(str(quantity)) * Decimal(str(price))
    if quote_amount == quote_amount.to_integral_value():
        quote_amount_value: int | float = int(quote_amount)
    else:
        quote_amount_value = float(quote_amount)
        if not math.isfinite(quote_amount_value):
            raise ValueError("quantity × average_price is outside the supported numeric range.")

    return {
        "pair": pair,
        "base_currency": base,
        "quote_currency": quote,
        "quantity_base_units": quantity,
        "average_price_quote_per_base": price,
        "price_label": _PRICE_LABEL,
        "currency_legs": {
            base: quantity,
            quote: -quote_amount_value,
        },
    }


def portfolio_fx_exposure(portfolio: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    """Calculate separately itemized FX legs from the repository portfolio format.

    ``portfolio`` may be a JSON file path or a mapping with a ``positions`` list.
    Recognized non-FX holdings in mixed portfolios are ignored; an FX holding
    without a valid quantity or supplied ``average_price`` is rejected.
    """
    if isinstance(portfolio, (str, Path)):
        try:
            data = json.loads(Path(portfolio).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read portfolio JSON: {exc}") from exc
    else:
        data = portfolio
    if not isinstance(data, Mapping) or not isinstance(data.get("positions"), list):
        raise ValueError("Portfolio must be an object containing a positions list.")

    positions = []
    for index, item in enumerate(data["positions"]):
        if not isinstance(item, Mapping):
            raise ValueError(f"Portfolio position {index} must be an object.")
        ticker = item.get("ticker")
        if not isinstance(ticker, str):
            raise ValueError(f"Portfolio position {index} must have a string ticker.")
        symbol = ticker.strip().upper()
        pair_symbol = symbol[:-2] if symbol.endswith("=X") else symbol
        if len(pair_symbol) == 6 and pair_symbol.isalpha() and pair_symbol[:3] in CURRENCIES and pair_symbol[3:] in CURRENCIES:
            positions.append(fx_position_exposure(item))

    return {
        "positions": positions,
        "assumptions": list(_ASSUMPTIONS),
    }
