import json

import pytest

from ta_claude.fx_exposure import fx_position_exposure, portfolio_fx_exposure


def test_fx_legs_use_base_units_and_supplied_average_price():
    result = fx_position_exposure({
        "ticker": "eurusd=X",
        "quantity": 100_000,
        "average_price": 1.08,
    })

    assert result["pair"] == "EURUSD"
    assert result["quantity_base_units"] == 100_000
    assert result["average_price_quote_per_base"] == 1.08
    assert result["currency_legs"] == {"EUR": 100_000, "USD": -108_000}
    assert "not current market price" in result["price_label"]


def test_short_fx_position_has_opposite_signed_legs():
    result = fx_position_exposure({
        "ticker": "USDJPY",
        "quantity": -2_500,
        "average_price": 150.0,
    })
    assert result["currency_legs"] == {"USD": -2_500, "JPY": 375_000.0}


def test_mixed_portfolio_keeps_fx_positions_separate_and_ignores_non_fx():
    result = portfolio_fx_exposure({"positions": [
        {"ticker": "NVDA", "quantity": 10, "average_price": 100},
        {"ticker": "EURUSD", "quantity": 100, "average_price": 1.1},
        {"ticker": "EURGBP=X", "quantity": -50, "average_price": 0.85},
    ]})

    assert [position["currency_legs"] for position in result["positions"]] == [
        {"EUR": 100, "USD": -110},
        {"EUR": -50, "GBP": 42.5},
    ]
    assert len(result["positions"]) == 2
    assert any("never netted" in assumption for assumption in result["assumptions"])


@pytest.mark.parametrize("position", [
    {"ticker": "AAPL", "quantity": 1, "average_price": 10},
    {"ticker": "ABCDEF", "quantity": 1, "average_price": 10},
    {"ticker": "EURUSD", "quantity": 1},
    {"ticker": "EURUSD", "quantity": 1, "average_price": 0},
    {"ticker": "EURUSD", "quantity": float("nan"), "average_price": 1},
    {"ticker": "EURUSD", "quantity": True, "average_price": 1},
    {"ticker": "EURUSD", "quantity": 0, "average_price": 1},
])
def test_invalid_or_non_fx_position_is_rejected(position):
    with pytest.raises(ValueError):
        fx_position_exposure(position)


def test_fx_position_in_portfolio_requires_valid_supplied_price():
    with pytest.raises(ValueError, match="average_price"):
        portfolio_fx_exposure({"positions": [
            {"ticker": "GBPUSD", "quantity": 1},
        ]})


def test_portfolio_can_be_loaded_from_existing_json_format(tmp_path):
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps({
        "cash": 50000,
        "currency": "USD",
        "positions": [{"ticker": "GBPUSD", "quantity": 4, "average_price": 1.25}],
    }))
    result = portfolio_fx_exposure(path)
    assert result["positions"][0]["currency_legs"] == {"GBP": 4, "USD": -5}


@pytest.mark.parametrize("portfolio", [None, {}, {"positions": {}}, {"positions": [None]}])
def test_malformed_portfolio_is_rejected(portfolio):
    with pytest.raises(ValueError):
        portfolio_fx_exposure(portfolio)
