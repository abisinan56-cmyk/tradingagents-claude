"""Live mode and ADX guard, offline."""
import json
from datetime import date

import pandas as pd
import pytest

from ta_claude import cli, live, runner
from ta_claude.config import build_config
from ta_claude.live import Intraday, LiveQuote, assess


def _intraday(last=12.30, bar="2026-11-04T09:55:00+00:00", prev=11.78):
    return Intraday(last, bar, 11.84, 12.42, 11.74, prev, "1m")


def test_assess_matching_screen_and_fresh_rating():
    q = LiveQuote("EMAAR.AE", 12.30, captured_at="2026-11-04T10:00:00+00:00")
    chk = assess(q, _intraday(), {"date": "2026-11-04", "rating": "Buy", "pending": True},
                 today=date(2026, 11, 4))
    assert chk.screen_vs_yahoo_pct == 0 and chk.yahoo_lag_minutes == 5.0
    assert chk.session_move_pct == pytest.approx(4.41, abs=0.01)
    assert chk.rating_age_days == 0
    assert not any("differs" in f or "old" in f for f in chk.flags)


def test_assess_flags_divergence_lag_and_stale_rating():
    q = LiveQuote("EMAAR.AE", 12.50, captured_at="2026-11-04T10:30:00+00:00")
    chk = assess(q, _intraday(), {"date": "2026-10-28", "rating": "Hold", "pending": False},
                 today=date(2026, 11, 4))
    text = " ".join(chk.flags)
    assert "differs from Yahoo by +1.63%" in text and "35 min" in text and "7 days old" in text


def test_assess_without_yahoo_data():
    chk = assess(LiveQuote("FAB.AD", 17.1), None, None)
    assert chk.yahoo is None and any("no intraday" in f for f in chk.flags)
    assert any("not on Yahoo" in f for f in chk.flags)


def test_yahoo_intraday_parses_bars(monkeypatch):
    idx = pd.date_range("2026-11-04 06:00", periods=3, freq="1min", tz="Asia/Dubai")
    bars = pd.DataFrame({"Open": [1.0, 1.1, 1.2], "High": [1.1, 1.3, 1.25],
                         "Low": [0.9, 1.0, 1.1], "Close": [1.05, 1.2, 1.22]}, index=idx)
    daily = pd.DataFrame({"Close": [1.0, 1.1]})

    class T:
        def __init__(self, s): pass
        def history(self, period, interval): return bars if interval == "1m" else daily

    import yfinance
    monkeypatch.setattr(yfinance, "Ticker", T)
    got = live.yahoo_intraday("X")
    assert (got.last, got.high, got.low, got.prev_close) == (1.22, 1.3, 0.9, 1.0)
    assert got.last_bar == "2026-11-04T02:02:00+00:00"


def test_yahoo_intraday_none_when_empty(monkeypatch):
    class T:
        def __init__(self, s): pass
        def history(self, period, interval): return pd.DataFrame({"Close": []})
    import yfinance
    monkeypatch.setattr(yfinance, "Ticker", T)
    assert live.yahoo_intraday("FAB.AD") is None


def test_latest_rating(tmp_path):
    from tradingagents.memory.log import TradingMemoryLog
    sep = TradingMemoryLog._SEPARATOR
    p = tmp_path / "m.md"
    p.write_text(sep.join([
        "[2026-10-01 | NVDA | Hold | +1.0% | +0.2% | 5d]\n\nDECISION:\nx",
        "[2026-11-03 | NVDA | Buy | pending]\n\nDECISION:\nx",
        "[2026-11-04 | AAPL | Sell | pending]\n\nDECISION:\nx",
    ]) + sep, encoding="utf-8")
    assert live.latest_rating("nvda", str(p)) == {"date": "2026-11-03", "rating": "Buy", "pending": True}
    assert live.latest_rating("MSFT", str(p)) is None


def test_cli_live(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(live, "yahoo_intraday", lambda s: _intraday())
    monkeypatch.setattr(live, "latest_rating", lambda s, p: None)
    q = tmp_path / "q.json"
    q.write_text(json.dumps({"symbol": "emaar.ae", "price": 12.3, "source": "tradingview.com",
                             "captured_at": "2026-11-04T10:00:00+00:00"}))
    assert cli.main(["live", "EMAAR.AE", "--quote", str(q), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["symbol"] == "EMAAR.AE" and out["screen_vs_yahoo_pct"] == 0 and out["fresh_run"] is None
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    assert cli.main(["live", "EMAAR.AE", "--price", "12.3", "--full"]) == 2


def test_adx_refused_for_agent_runs(tmp_path):
    cfg = build_config(); cfg["memory_log_path"] = str(tmp_path / "m.md")
    with pytest.raises(ValueError, match="not on Yahoo"):
        runner.run_report("FAB.AD", "2026-11-04", cfg, use_replay=False)
    with pytest.raises(ValueError, match="not on Yahoo"):
        runner.run_backtest_job(["NVDA", "FAB.AD"], "2026-07-06", "2026-07-20", 7, cfg)
