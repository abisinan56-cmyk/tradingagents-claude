from datetime import datetime, timedelta, timezone

import pytest

from ta_claude.model import PriceBar, _rsi, _strategy_direction, parse_yahoo_chart, technical_analysis, scan_fx


def test_chart_filters_recent_bar_and_adjusts_all_ohlc():
    now = datetime(2026, 7, 6, 12, tzinfo=timezone.utc)
    payload = {"chart": {"result": [{"timestamp": [(now - timedelta(days=4)).timestamp(), now.timestamp()],
        "indicators": {"quote": [{"open": [100, 100], "high": [110, 110], "low": [90, 90], "close": [100, 100]}],
                       "adjclose": [{"adjclose": [50, 50]}]}}]}}
    bars = parse_yahoo_chart(payload, now=now)
    assert bars == [PriceBar('2026-07-02', 50, 50, 55, 45)]


def test_flat_rsi_and_candle_are_not_directional():
    bars = [PriceBar('2026-01-01', 1, 1, 1.2, .8) for _ in range(60)]
    assert _rsi([1.0] * 60) == 50
    assert _strategy_direction('rsi_momentum', bars) == 0
    patterns = technical_analysis(bars)['last_candle']['patterns']
    assert patterns == ['doji (indecision)']


def test_missing_ohlc_is_not_a_fabricated_candle():
    bars = [PriceBar('2026-01-01', 1) for _ in range(60)]
    with pytest.raises(ValueError, match='OHLC data is incomplete'):
        technical_analysis(bars)


def test_fx_scan_rejects_non_fx_without_fetch(monkeypatch):
    from ta_claude import model
    monkeypatch.setattr(model, 'fetch_daily_history', lambda *a: pytest.fail('must not fetch'))
    with pytest.raises(ValueError, match='No FX pair histories'):
        scan_fx(['AAPL'])


def test_stale_plan_warns_and_exposes_source_age():
    from ta_claude.model import build_trade_plan
    bars = [PriceBar((datetime(2020, 1, 1) + timedelta(days=i)).date().isoformat(), 100+i)
            for i in range(60)]
    assert any('calendar days old' in warning for warning in build_trade_plan('EURUSD', bars).warnings)


def test_chart_uses_exchange_timezone_for_session_date():
    now = datetime(2026, 7, 6, tzinfo=timezone.utc)
    stamp = datetime(2026, 7, 2, 1, tzinfo=timezone.utc).timestamp()
    payload = {'chart': {'result': [{'timestamp': [stamp], 'meta': {'exchangeTimezoneName': 'America/New_York'},
                    'indicators': {'quote': [{'close': [1], 'open': [1], 'high': [1], 'low': [1]}]}}]}}
    assert parse_yahoo_chart(payload, now=now)[0].day == '2026-07-01'


def test_integrated_backtests_never_use_post_end_prices():
    from ta_claude.model import backtest_strategy, backtest_trend
    start = datetime(2020, 1, 1)
    bars = [PriceBar((start + timedelta(days=i)).date().isoformat(), 100 + i, 100 + i, 101 + i, 99 + i)
            for i in range(80)]
    changed = bars.copy()
    changed[71] = PriceBar(bars[71].day, 10000, 10000, 10000, 10000)
    for fn in (lambda b: backtest_trend('EURUSD', b, bars[55].day, bars[70].day).total_return_pct,
               lambda b: backtest_strategy('EURUSD', b, bars[55].day, bars[70].day, 'trend')['total_return_pct']):
        assert fn(bars) == fn(changed)


def test_breakout_does_not_fabricate_missing_historical_high_low():
    bars = [PriceBar('2026-01-01', 1) for _ in range(60)]
    with pytest.raises(ValueError, match='requires historical high and low'):
        _strategy_direction('breakout', bars)
