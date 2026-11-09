"""The deterministic technical snapshot feeds the upstream agent run, look-ahead-safe and replayable."""
from datetime import date, timedelta

from ta_claude import model, runner
from ta_claude.model import PriceBar, build_trade_plan, scan_fx, technical_snapshot
from ta_claude.replay import replay


def _bars(n=120, start=date(2026, 1, 1), step=0.2):
    return [PriceBar((start + timedelta(days=i)).isoformat(), 100 + i * step,
                     100 + i * step - 0.1, 100 + i * step + 0.3, 100 + i * step - 0.3) for i in range(n)]


def test_snapshot_uses_only_bars_up_to_trade_date(monkeypatch):
    bars = _bars()
    seen = {}

    def fake_rows(symbol, start, end):
        seen["end"] = end
        return [vars(b) for b in bars]  # includes bars after ``end``; fetch_daily_history must cut them

    monkeypatch.setattr(model, "fetch_daily_rows", fake_rows)
    text = technical_snapshot("EURUSD", bars[80].day)
    assert seen["end"] == bars[80].day
    assert f"through {bars[80].day}" in text
    assert "RSI14" in text and "ATR14" in text and "20/50 trend regime: long" in text
    assert "Model reference levels" in text and "stop" in text


def test_snapshot_is_none_when_data_is_unavailable(monkeypatch):
    monkeypatch.setattr(model, "fetch_daily_rows", lambda *a: (_ for _ in ()).throw(ValueError("down")))
    assert technical_snapshot("EURUSD", "2026-05-01") is None


def test_graph_appends_snapshot_to_instrument_context(monkeypatch):
    class Base:
        def __init__(self, analysts, config): pass
        def resolve_instrument_context(self, ticker, asset_type="stock", trade_date=None):
            return f"base:{ticker}"

    monkeypatch.setattr(runner, "TradingAgentsGraph", Base)
    monkeypatch.setattr(model, "technical_snapshot", lambda t, d: "SNAPSHOT")
    graph = runner.TaClaudeGraph(["market"], config={})
    assert graph.resolve_instrument_context("EURUSD=X", "crypto", "2026-05-01") == "base:EURUSD=X\n\nSNAPSHOT"
    assert graph.resolve_instrument_context("EURUSD=X", "crypto", None) == "base:EURUSD=X"
    monkeypatch.setattr(model, "technical_snapshot", lambda t, d: None)
    assert graph.resolve_instrument_context("EURUSD=X", "crypto", "2026-05-01") == "base:EURUSD=X"


def test_snapshot_fetch_is_recorded_and_replayed(tmp_path, monkeypatch):
    calls = []
    rows = [vars(b) for b in _bars()]
    monkeypatch.setattr(model, "fetch_daily_rows", lambda *a: calls.append(a) or rows)
    with replay(tmp_path / "r.db"):
        first = model.fetch_daily_history("EURUSD", "2026-01-01", "2026-04-30")
    monkeypatch.setattr(model, "fetch_daily_rows", lambda *a: (_ for _ in ()).throw(AssertionError("network")))
    with replay(tmp_path / "r.db"):
        second = model.fetch_daily_history("EURUSD", "2026-01-01", "2026-04-30")
    assert first == second and len(calls) == 1


def test_stop_is_atr_based_and_fx_scale_friendly():
    # EUR/USD-like scale: 1.5x ATR14 on 0.004-wide bars is ~0.5%, far below the old 2% floor.
    bars = [PriceBar((date(2026, 1, 1) + timedelta(days=i)).isoformat(), 1.10 + i * 0.001,
                     1.10 + i * 0.001 - 0.001, 1.10 + i * 0.001 + 0.002, 1.10 + i * 0.001 - 0.002)
            for i in range(80)]
    plan = build_trade_plan("EURUSD", bars)
    assert plan.action == "long"
    assert 0.3 <= plan.risk_per_unit_pct < 1.0
    assert "1.5x ATR(14)" in plan.technical_signal
    assert any("ATR(14)" in line for line in plan.rationale)


def test_scan_reports_strength_only_for_directional_pairs(monkeypatch):
    def rows_for(symbol, start, end):
        if symbol.startswith("EURUSD"):
            return [vars(b) for b in _bars()]
        # Oscillating series: no 20/50 alignment, so flat
        return [vars(PriceBar((date(2026, 1, 1) + timedelta(days=i)).isoformat(), 100 + (i % 2),
                               100 + (i % 2), 101 + (i % 2), 99 + (i % 2))) for i in range(120)]

    monkeypatch.setattr(model, "fetch_daily_rows", rows_for)
    scan = scan_fx(["GBPUSD", "EURUSD"])
    assert [c["ticker"] for c in scan.candidates] == ["EURUSD=X", "GBPUSD=X"]
    assert scan.candidates[0]["trend_strength"] > 0
    assert scan.candidates[1]["action"] == "flat" and scan.candidates[1]["trend_strength"] is None
