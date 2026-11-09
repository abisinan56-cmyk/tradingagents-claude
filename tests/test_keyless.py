"""Everything works with no API key: research pack, keyless news, and fallbacks."""
import json
from datetime import date, timedelta

import pytest

from ta_claude import cli, model, research
from ta_claude.model import PriceBar


def _rows(n=120):
    start = date(2026, 6, 1)
    return [vars(PriceBar((start + timedelta(days=i)).isoformat(), 1.10 + i * 0.001, 1.10 + i * 0.001 - 0.001,
                          1.10 + i * 0.001 + 0.002, 1.10 + i * 0.001 - 0.002)) for i in range(n)]


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(model, "fetch_daily_rows", lambda *a: _rows())
    monkeypatch.setattr(research, "fetch_news", lambda s, d, limit=8: [
        {"date": "2026-09-27", "title": "EUR/USD awaits US CPI", "source": "FX Empire", "url": "https://x/y"},
        {"date": "2026-12-01", "title": "future item", "source": "s", "url": None}][:1])


def test_research_pack_has_data_and_instructions_for_the_session(offline):
    pack = research.build_research_pack("EURUSD", "2026-09-28")
    assert pack["mode"] == "keyless" and pack["ticker"] == "EURUSD=X" and pack["market"] == "fx"
    assert "through 2026-09-28" in pack["technical_snapshot"]
    assert pack["plan"]["action"] == "long" and "fx_brief" in pack
    assert pack["news"][0]["source"] == "FX Empire"
    assert pack["calendar_currencies"] == ["EUR", "USD"]
    assert any("Firecrawl connector" in step for step in pack["connector_steps"])
    assert any("Keyless TradingAgents" in step for step in pack["analysis_steps"])


def test_research_pack_survives_news_failure(offline, monkeypatch):
    monkeypatch.setattr(research, "fetch_news", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("blocked")))
    pack = research.build_research_pack("EURUSD", "2026-09-28")
    assert pack["news"] == [] and any("news unavailable" in w for w in pack["warnings"])


def test_news_drops_items_after_the_analysis_date(monkeypatch):
    class FakeTicker:
        def __init__(self, symbol):
            self.news = [{"content": {"pubDate": "2026-09-27T07:00:00Z", "title": "old",
                                      "provider": {"displayName": "A"}, "canonicalUrl": {"url": "u1"}}},
                         {"content": {"pubDate": "2026-10-02T07:00:00Z", "title": "later",
                                      "provider": {"displayName": "B"}, "canonicalUrl": {"url": "u2"}}}]

    import yfinance
    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)
    assert [n["title"] for n in research.fetch_news("EURUSD=X", "2026-09-28")] == ["old"]


def test_research_command_and_with_news_need_no_key(offline, capsys):
    assert cli.main(["research", "EURUSD", "--date", "2026-09-28", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "keyless"
    assert cli.main(["fx-brief", "EURUSD", "--with-news", "--json"]) == 0
    news = json.loads(capsys.readouterr().out)["news_research"]
    assert news["mode"] == "keyless" and news["news"] and news["calendar_currencies"] == ["EUR", "USD"]


def test_adx_is_still_refused_in_keyless_mode(offline):
    with pytest.raises(ValueError, match="not on Yahoo"):
        research.build_research_pack("FAB.AD", "2026-09-28")
