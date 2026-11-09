"""Time machine, risk check and journal: the plan-discipline layer, all offline."""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from ta_claude import journal
from ta_claude.model import PriceBar, build_trade_plan
from ta_claude.risk import DEFAULT_LIMITS, check_plan, load_limits
from ta_claude.timemachine import run_time_machine, verdict_line


def _bars(n=320, drift=0.001, wick=0.004, start=date(2025, 1, 1)):
    bars, price = [], 1.10
    for i in range(n):
        o = price
        c = price * (1 + drift * (1 if i % 3 else -1))
        bars.append(PriceBar((start + timedelta(days=i)).isoformat(), c, o, max(o, c) * (1 + wick), min(o, c) * (1 - wick)))
        price = c
    return bars


def test_time_machine_is_deterministic_and_sums_to_100():
    bars = _bars()
    plan = build_trade_plan("EURUSD", bars)
    assert plan.action == "long"
    a = run_time_machine("EURUSD=X", bars, plan.entry_reference, plan.stop_reference, plan.target_reference,
                         plan.action, replays=500)
    b = run_time_machine("EURUSD=X", bars, plan.entry_reference, plan.stop_reference, plan.target_reference,
                         plan.action, replays=500)
    assert a == b
    assert round(a.target_first_pct + a.stop_first_pct + a.neither_pct, 1) == 100.0
    assert a.reward_risk == 2.0 and a.seed == 19 and a.pool_days >= 60
    assert a.history["fired"] > 0 and "Real past bars" in a.history["note"]


def test_time_machine_stop_wins_a_tie_and_refuses_bad_plans():
    bars = _bars(n=100, wick=0.5)  # every bar touches both sides: the stop must win
    tm = run_time_machine("EURUSD=X", bars, 1.0, 0.99, 1.02, "long", replays=200)
    assert tm.stop_first_pct == 100.0 and tm.average_r == -1.0
    with pytest.raises(ValueError, match="flat plan"):
        run_time_machine("EURUSD=X", bars, 1.0, 0.99, 1.02, "flat")
    with pytest.raises(ValueError, match="losing side"):
        run_time_machine("EURUSD=X", bars, 1.0, 1.01, 1.02, "long")
    with pytest.raises(ValueError, match="at least 60"):
        run_time_machine("EURUSD=X", bars[:40], 1.0, 0.99, 1.02, "long")


def test_verdict_uses_break_even_for_the_reward_risk():
    assert verdict_line(50, 50, 1.0).startswith("Close to a coin flip")
    assert verdict_line(24.1, 50.5, 2.0).startswith("Close to break-even")  # 32% of decided vs 33% needed
    assert verdict_line(60, 20, 1.0).startswith("Strongly toward the target")
    assert verdict_line(25, 68, 2.0).startswith("Leans toward the stop")


def _plan(action="long", entry=1.10, stop=1.09, target=1.12, as_of="2026-11-06"):
    return {"ticker": "EURUSD=X", "as_of": as_of, "action": action, "entry_reference": entry,
            "stop_reference": stop, "target_reference": target, "warnings": []}


def test_risk_passes_and_sizes_within_limits():
    v = check_plan(_plan(), DEFAULT_LIMITS, today=date(2026, 11, 6))
    assert v.passed and v.status == "PASS"
    # 1% of 5000 = 50 at 0.01 risk per unit = 5000 units, cut to the 20% cap (1000 / 1.10 = 909)
    assert v.position_units == 909 and v.max_loss_at_stop == 9.09
    assert any("position cap" in w for w in v.warnings)


def test_risk_blocks_each_limit_with_a_reason():
    limits = {**DEFAULT_LIMITS, "max_position_pct": 100}
    assert not check_plan(_plan("flat", stop=None, target=None), limits).passed
    assert "wrong side" in check_plan(_plan(stop=1.11), limits).reasons[0]
    assert any("Reward:risk" in r for r in check_plan(_plan(target=1.105), limits).reasons)
    today = [{"action": "long", "max_loss_at_stop": 50}] * 3
    r = check_plan(_plan(), limits, journal_today=today, today=date(2026, 11, 6)).reasons
    assert any("trades already" in x for x in r) and any("daily loss" in x for x in r)
    cal = [{"currency": "USD", "title": "CPI", "hours_away": 5}]
    assert any("High-impact USD event" in x for x in check_plan(_plan(), limits, calendar=cal).reasons)
    tm = {"verdict": "Leans toward the stop: ..."}
    assert any("leans toward the stop" in x for x in check_plan(_plan(), limits, time_machine=tm).reasons)
    assert "blocked list" in check_plan(_plan(), {**limits, "blocked": ["EURUSD=X"]}).reasons[0]


def test_limits_file_overrides_defaults_and_validates(tmp_path):
    f = tmp_path / "risk.json"
    f.write_text(json.dumps({"budget": 20000, "min_reward_risk": 1.0}))
    limits = load_limits(f)
    assert limits["budget"] == 20000 and limits["max_trades_per_day"] == 3
    f.write_text(json.dumps({"budget": -1}))
    with pytest.raises(ValueError, match="positive number"):
        load_limits(f)


def test_journal_records_and_scores_against_real_bars(tmp_path):
    path = tmp_path / "journal.jsonl"
    now = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)
    entry = journal.record(_plan(), {"status": "PASS", "max_loss_at_stop": 9.09}, "test", path, 909, now)
    assert entry["outcome"] is None and journal.today_entries(path, now.date()) == [entry]

    def fake_fetch(ticker, start, end):  # target 1.12 is touched on day 3
        base = date(2026, 11, 6)
        highs = [1.105, 1.11, 1.125] + [1.11] * 20
        return [PriceBar((base + timedelta(days=i + 1)).isoformat(), 1.10, 1.10, highs[i], 1.095) for i in range(23)]

    out = journal.score(path, fetch=fake_fetch)
    assert out["scored"] == 1 and out["target_first"] == 1 and out["average_r"] == 2.0
    assert "too few" in out["note"]
    scored = json.loads(path.read_text().splitlines()[0])
    assert scored["outcome"] == "target" and scored["r"] == 2.0


def test_journal_waits_for_the_window_to_close(tmp_path):
    path = tmp_path / "journal.jsonl"
    journal.record(_plan(), None, "", path, now=datetime(2026, 11, 6, tzinfo=timezone.utc))
    short = lambda t, s, e: [PriceBar("2026-11-07", 1.10, 1.10, 1.105, 1.095)]  # noqa: E731
    out = journal.score(path, fetch=short)
    assert out["scored"] == 0 and len(out["open"]) == 1


def test_cli_timemachine_risk_and_journal_run_offline(monkeypatch, capsys, tmp_path):
    from ta_claude import cli, journal as jn, model, risk
    bars = _bars()
    monkeypatch.setattr(model, "fetch_daily_rows", lambda *a: [vars(b) for b in bars])
    monkeypatch.setattr(jn, "JOURNAL", tmp_path / "journal.jsonl")
    monkeypatch.setattr(risk, "RISK_FILE", tmp_path / "risk.json")
    assert cli.main(["timemachine", "EURUSD", "--date", bars[-1].day, "--replays", "300", "--json"]) == 0
    tm = json.loads(capsys.readouterr().out)
    assert tm["replays"] == 300 and "verdict" in tm
    assert cli.main(["risk", "EURUSD", "--date", bars[-1].day, "--record", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] in ("PASS", "BLOCK") and out["plan"]["action"] == "long"
    if out["status"] == "PASS":
        assert out["journal_entry"]["ticker"] == "EURUSD=X"
    assert cli.main(["journal", "show", "--json"]) == 0
    assert "entries" in json.loads(capsys.readouterr().out)
