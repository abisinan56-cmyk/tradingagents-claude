"""Offline tests: no API key or network needed."""
from datetime import date

import pytest

from ta_claude import cutoff, runner
from ta_claude.config import build_config
from ta_claude.markets import backtest_analysts, classify


@pytest.mark.parametrize("ticker,market,asset,sym", [
    ("NVDA", "us", "stock", "NVDA"),
    ("BRK.B", "us", "stock", "BRK.B"),
    ("EMAAR.AE", "uae", "stock", "EMAAR.AE"),
    ("RELIANCE.NS", "india", "stock", "RELIANCE.NS"),
    ("BTC-USD", "crypto", "crypto", "BTC-USD"),
    ("EURUSD", "fx", "crypto", "EURUSD=X"),
    ("GBPJPY=X", "fx", "crypto", "GBPJPY=X"),
    ("USDAED", "fx", "crypto", "USDAED=X"),
])
def test_classify(ticker, market, asset, sym):
    m = classify(ticker)
    assert (m.name, m.asset_type, m.symbol) == (market, asset, sym)


def test_pegged_fx_warns_and_fx_has_no_fundamentals():
    m = classify("USDAED")
    assert any("pegged" in w for w in m.warnings)
    assert "fundamentals" not in m.analysts


def test_backtest_drops_social():
    assert "social" not in backtest_analysts(classify("NVDA"))


def test_benchmarks():
    from tradingagents.memory.settlement import resolve_benchmark
    cfg = build_config()
    assert resolve_benchmark("EMAAR.AE", cfg) == "UAE"
    assert resolve_benchmark("EURUSD=X", cfg) == "DX-Y.NYB"
    assert resolve_benchmark("RELIANCE.NS", cfg) == "^NSEI"
    assert resolve_benchmark("NVDA", cfg) == "SPY"
    assert cfg["llm_provider"] == "anthropic" and cfg["temperature"] == 0.0


def test_cutoff_guard(monkeypatch):
    monkeypatch.delenv("TA_MODEL_CUTOFF", raising=False)
    with pytest.raises(cutoff.CutoffError):
        cutoff.check_dates(["2026-05-01"], ["claude-opus-5-5", "claude-sonnet-5"])
    notes = cutoff.check_dates(["2026-07-07"], ["claude-opus-5-5", "claude-sonnet-5"])
    assert any("conservative" in n for n in notes)
    notes = cutoff.check_dates(["2026-05-01"], ["claude-opus-5-5"], allow_contaminated=True)
    assert any("contaminated" in n for n in notes)
    with pytest.raises(cutoff.CutoffError):
        cutoff.model_cutoff("gpt-something")


def _write_log(path, rows):
    from tradingagents.memory.log import TradingMemoryLog
    sep = TradingMemoryLog._SEPARATOR
    body = sep.join(f"[{d} | {t} | {r} | {raw} | {a} | 5d]\n\nDECISION:\nx" for d, t, r, raw, a in rows)
    path.write_text(body + sep, encoding="utf-8")


def test_score_log(tmp_path):
    log = tmp_path / "log.md"
    _write_log(log, [
        ("2026-07-07", "NVDA", "Buy", "+2.0%", "+1.0%"),
        ("2026-07-14", "NVDA", "Sell", "-3.0%", "-2.0%"),
        ("2026-07-21", "NVDA", "Hold", "+1.0%", "+0.5%"),
        ("2026-07-28", "NVDA", "Underweight", "+1.0%", "+0.0%"),
        ("2026-08-04", "NVDA", "Overweight", "+0.5%", "+0.1%"),
    ])
    rep = runner.score_log(log, cost_bps=10)
    assert rep.scored == 5
    # nets: .02-.001, .03-.001, 0, -.01-.001, .005-.001
    assert rep.strategy_mean == pytest.approx((0.019 + 0.029 + 0 - 0.011 + 0.004) / 5)
    assert rep.hit_rate == pytest.approx(3 / 4)
    assert rep.benchmark_mean == pytest.approx((0.01 - 0.01 + 0.005 + 0.01 + 0.004) / 5)
    assert "too few" in rep.render()


def test_replay_freezes_data_calls(tmp_path, monkeypatch):
    import tradingagents.agents.tools as tools_mod
    from ta_claude.replay import replay

    calls = []
    monkeypatch.setattr(tools_mod, "route_to_vendor", lambda m, *a, **k: calls.append(m) or f"live-{len(calls)}")
    with replay(tmp_path / "r.db"):
        first = tools_mod.route_to_vendor("get_news", "NVDA")
    with replay(tmp_path / "r.db"):
        second = tools_mod.route_to_vendor("get_news", "NVDA")
    assert first == second == "live-1" and calls == ["get_news"]


def test_replay_llm_cache_roundtrip(tmp_path):
    from langchain_core.outputs import ChatGeneration
    from langchain_core.messages import AIMessage
    from ta_claude.replay import SQLiteLLMCache, _Store

    cache = SQLiteLLMCache(_Store(tmp_path / "c.db"))
    gen = [ChatGeneration(message=AIMessage(content="Rating: Buy",
                                            tool_calls=[{"name": "t", "args": {"a": 1}, "id": "1"}]))]
    cache.update("p", "llm", gen)
    got = cache.lookup("p", "llm")
    assert got[0].message.content == "Rating: Buy" and got[0].message.tool_calls[0]["args"] == {"a": 1}
    assert cache.lookup("other", "llm") is None


def test_ensemble_vote(tmp_path, monkeypatch):
    seq = iter(["Buy", "Buy", "Hold", "REVIEW", "Buy"])
    stored, saved = [], []

    class FakeLog:
        def store_decision(self, **kw): stored.append(kw)

    class FakeGraph:
        def __init__(self, analysts, config): self.memory_log = FakeLog()
        def settle_pending(self, t): pass
        def propagate(self, t, d, a, portfolio=None):
            r = next(seq); return {"final_trade_decision": f"Rating: {r}"}, r
        def save_reports(self, s, t): saved.append(s); return tmp_path

    monkeypatch.setattr(runner, "TradingAgentsGraph", FakeGraph)
    cfg = build_config()
    cfg["memory_log_path"] = str(tmp_path / "mem.md")
    res = runner.run_ensemble("NVDA", "2026-11-03", cfg, n=5)
    assert res.rating == "Buy" and res.agreement == 0.6 and res.confidence == "medium"
    assert res.votes == {"Buy": 3, "Hold": 1, "REVIEW": 1}
    assert len(stored) == 1 and stored[0]["rating"] == "Buy"
