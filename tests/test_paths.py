"""End-to-end paths with the graph and vendors faked: no API key or network."""
import importlib
import json
from pathlib import Path

import pytest

from ta_claude import cli, config as config_mod, runner
from ta_claude.config import build_config
from ta_claude.replay import DATA_ENTRY_POINTS, replay

ROOT = Path(__file__).resolve().parents[1]


def test_replay_patches_and_restores_every_data_entry_point(tmp_path):
    originals = {(m, a): getattr(importlib.import_module(m), a) for m, a in DATA_ENTRY_POINTS}
    with replay(tmp_path / "r.db"):
        for (m, a), fn in originals.items():
            assert getattr(importlib.import_module(m), a) is not fn, f"{m}.{a} not patched"
    for (m, a), fn in originals.items():
        assert getattr(importlib.import_module(m), a) is fn, f"{m}.{a} not restored"


def test_replay_does_not_cache_non_json_results(tmp_path, monkeypatch):
    import tradingagents.agents.context as ctx
    calls = []
    monkeypatch.setattr(ctx, "get_company_profile", lambda t: calls.append(t) or {"when": object()})
    with replay(tmp_path / "r.db"):
        ctx.get_company_profile("X"); ctx.get_company_profile("X")
    assert len(calls) == 2  # an object is not JSON: passed through, never stored


class FakeLog:
    def __init__(self, path): self.path = Path(path)
    def store_decision(self, **kw):
        with self.path.open("a", encoding="utf-8") as f:
            f.write(f"[{kw['trade_date']} | {kw['ticker']} | {kw['rating']} | pending]\n")


def make_fake_graph(seen):
    class FakeGraph:
        def __init__(self, analysts, config):
            self.config = config
            self.memory_log = FakeLog(config["memory_log_path"])
            seen.append(config["memory_log_path"])
        def propagate(self, t, d, a, portfolio=None):
            self.memory_log.store_decision(ticker=t, trade_date=d, rating="Buy")
            return {"final_trade_decision": "Rating: Buy"}, "Buy"
        def save_reports(self, s, t, html=True): return Path("/tmp/report")
    return FakeGraph


def test_report_records_then_replays_without_touching_main_log(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "HOME", tmp_path)
    seen = []
    monkeypatch.setattr(runner, "TradingAgentsGraph", make_fake_graph(seen))
    cfg = build_config()
    main = tmp_path / "memory.md"
    main.write_text("old lesson\n", encoding="utf-8")
    cfg["memory_log_path"] = str(main)

    first = runner.run_report("NVDA", "2026-11-03", cfg)
    assert first["replayed"] is False and seen[-1] == str(main)
    assert "NVDA" in main.read_text()                       # first run records the decision
    after_first = main.read_text()

    second = runner.run_report("NVDA", "2026-11-03", cfg)
    assert second["replayed"] is True and seen[-1] != str(main)
    assert main.read_text() == after_first                  # replay leaves the real log alone
    snap = next((tmp_path / "replay").glob("*.memory.md")).read_text()
    assert snap == "old lesson\n"                           # snapshot is the pre-run log

    third = runner.run_report("NVDA", "2026-11-03", cfg, analysts=["market"])
    assert third["replayed"] is False                       # different settings, new recording


def test_crashed_first_run_is_not_treated_as_a_recording(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "HOME", tmp_path)
    class Boom:
        def __init__(self, *a, **k): pass
        def propagate(self, *a, **k): raise RuntimeError("vendor down")
    monkeypatch.setattr(runner, "TradingAgentsGraph", Boom)
    cfg = build_config(); cfg["memory_log_path"] = str(tmp_path / "m.md")
    with pytest.raises(RuntimeError):
        runner.run_report("NVDA", "2026-11-03", cfg)
    seen = []
    monkeypatch.setattr(runner, "TradingAgentsGraph", make_fake_graph(seen))
    assert runner.run_report("NVDA", "2026-11-03", cfg)["replayed"] is False


def _log(path, rows):
    from tradingagents.memory.log import TradingMemoryLog
    sep = TradingMemoryLog._SEPARATOR
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sep.join(f"[{d} | {t} | {r} | {raw} | {a} | 5d]\n\nDECISION:\nx"
                             for d, t, r, raw, a in rows) + sep, encoding="utf-8")


def test_backtest_job_groups_pipelines_merges_and_scores(tmp_path, monkeypatch):
    import tradingagents.backtest as bt
    calls = []

    def fake_run_backtest(tickers, dates, config, asset_type, portfolio, selected_analysts, run_id, progress):
        calls.append((tuple(tickers), asset_type, tuple(selected_analysts)))
        log = tmp_path / f"{run_id}.md"
        _log(log, [(d, t, "Buy", "+1.0%", "+0.5%") for t in tickers for d in dates[:2]])
        return bt.BacktestResult(run_id=run_id, log_path=log)

    monkeypatch.setattr(bt, "run_backtest", fake_run_backtest)
    cfg = build_config(); cfg["results_dir"] = str(tmp_path)
    rep, merged = runner.run_backtest_job(["NVDA", "AAPL", "EURUSD", "EMAAR.AE"],
                                          "2026-07-06", "2026-08-03", 7, cfg)
    groups = {c[0]: c for c in calls}
    # US and UAE stocks share one pipeline once social is dropped; FX runs on its own.
    assert groups[("NVDA", "AAPL", "EMAAR.AE")][1:] == ("stock", ("market", "news", "fundamentals"))
    assert groups[("EURUSD=X",)][1:] == ("crypto", ("market", "news"))
    assert len(calls) == 2
    assert rep.cells == rep.scored == 8                        # 4 tickers x 2 dates, merged intact
    assert rep.strategy_mean == pytest.approx(0.01 - 0.001)
    assert any("cutoff" in n for n in rep.notes)


def test_backtest_job_blocks_precutoff_dates(tmp_path):
    cfg = build_config(); cfg["results_dir"] = str(tmp_path)
    with pytest.raises(Exception, match="cutoff"):
        runner.run_backtest_job(["NVDA"], "2026-03-02", "2026-04-06", 7, cfg)


def test_portfolio_example_validates():
    pf = runner.load_portfolio(str(ROOT / "examples" / "portfolio.example.json"))
    assert pf.cash == 50000 and pf.positions_in("NVDA")


def test_cli_paths(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(runner, "run_report", lambda *a, **k: {
        "ticker": "NVDA", "market": "us", "date": "d", "rating": "Buy", "report_dir": "/r",
        "analysts": [], "replayed": False, "warnings": []})
    monkeypatch.setattr(runner, "run_ensemble", lambda *a, **k: runner.EnsembleResult(
        "NVDA", "d", "Buy", 0.8, {"Buy": 4, "Hold": 1}, "/r"))
    monkeypatch.setattr(runner, "run_backtest_job", lambda *a, **k: (runner.BacktestReport(1, 0, 1, 10.0), "/log"))
    assert cli.main(["report", "NVDA", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["rating"] == "Buy"
    assert cli.main(["ensemble", "NVDA", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["confidence"] == "high"
    assert cli.main(["backtest", "NVDA", "--start", "2026-07-06", "--end", "2026-07-20", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["log"] == "/log"
    assert cli.main(["market", "EURUSD"]) == 0
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    assert cli.main(["report", "NVDA"]) == 2


def test_skill_frontmatter():
    text = (ROOT / "skill" / "trading-agents" / "SKILL.md").read_text()
    head = text.split("---")[1]
    assert "name: trading-agents" in head and "description:" in head
