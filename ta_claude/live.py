"""Live mode: check a price read off the user's screen against Yahoo and the last rating.

The skill reads the quote from whatever stock page or app the user has open and
passes it here. Agents only ever see Yahoo's feed, which can lag the screen (DFM
and many non-US venues are delayed), so this module says how far the two differ
and how stale the last rating is before anyone acts on a "live" read.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from tradingagents.memory.log import TradingMemoryLog

from .markets import classify


@dataclass
class LiveQuote:
    symbol: str
    price: float
    source: str = ""                 # page URL or app name the price was read from
    captured_at: str = ""            # ISO time the screen was read; defaults to now
    change_pct: float | None = None  # as shown on screen, e.g. -1.2 for -1.2%
    currency: str | None = None

    @classmethod
    def load(cls, path: str) -> "LiveQuote":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})

    def captured(self) -> datetime:
        if self.captured_at:
            t = datetime.fromisoformat(self.captured_at.replace("Z", "+00:00"))
            return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc)


@dataclass
class Intraday:
    last: float
    last_bar: str        # ISO UTC time of the latest bar
    open: float
    high: float
    low: float
    prev_close: float | None
    interval: str


def yahoo_intraday(symbol: str) -> Intraday | None:
    """Latest intraday bars from Yahoo, or None when Yahoo has nothing (e.g. ADX)."""
    import yfinance as yf

    t = yf.Ticker(symbol)
    for interval in ("1m", "5m"):
        try:
            bars = t.history(period="1d", interval=interval).dropna(subset=["Close"])
        except Exception:
            bars = None
        if bars is not None and len(bars):
            break
    else:
        return None
    try:
        daily = t.history(period="5d", interval="1d")
        prev = float(daily["Close"].iloc[-2]) if len(daily) > 1 else None
    except Exception:
        prev = None
    stamp = bars.index[-1].to_pydatetime().astimezone(timezone.utc)
    return Intraday(float(bars["Close"].iloc[-1]), stamp.isoformat(), float(bars["Open"].iloc[0]),
                    float(bars["High"].max()), float(bars["Low"].min()), prev, interval)


def latest_rating(symbol: str, log_path: str) -> dict | None:
    entries = [e for e in TradingMemoryLog({"memory_log_path": log_path}).load_entries()
               if e["ticker"].upper() == symbol.upper()]
    if not entries:
        return None
    e = max(entries, key=lambda x: x["date"])
    return {"date": e["date"], "rating": e["rating"], "pending": e["pending"]}


@dataclass
class LiveCheck:
    symbol: str
    market: str
    screen: dict
    yahoo: dict | None
    last_rating: dict | None
    screen_vs_yahoo_pct: float | None = None
    yahoo_lag_minutes: float | None = None
    session_move_pct: float | None = None
    rating_age_days: int | None = None
    flags: list[str] = field(default_factory=list)


def assess(quote: LiveQuote, intraday: Intraday | None, last: dict | None,
           today: date | None = None, warnings: list[str] | None = None) -> LiveCheck:
    m = classify(quote.symbol)
    chk = LiveCheck(m.symbol, m.name, asdict(quote), asdict(intraday) if intraday else None, last,
                    flags=list(warnings or m.warnings))
    if intraday:
        chk.screen_vs_yahoo_pct = round((quote.price / intraday.last - 1) * 100, 3)
        lag = (quote.captured() - datetime.fromisoformat(intraday.last_bar)).total_seconds() / 60
        chk.yahoo_lag_minutes = round(lag, 1)
        if intraday.prev_close:
            chk.session_move_pct = round((quote.price / intraday.prev_close - 1) * 100, 2)
        if abs(chk.screen_vs_yahoo_pct) > 0.5:
            chk.flags.append(f"Screen price differs from Yahoo by {chk.screen_vs_yahoo_pct:+.2f}%: "
                             "the agents see Yahoo's (likely delayed) feed, not your screen.")
        if lag > 20:
            chk.flags.append(f"Yahoo's latest bar is {lag:.0f} min older than your screen read "
                             "(delayed feed or market closed).")
    else:
        chk.flags.append("Yahoo has no intraday data for this symbol: only the screen read is available.")
    if last:
        chk.rating_age_days = ((today or date.today()) - date.fromisoformat(last["date"])).days
        if chk.rating_age_days > 1:
            chk.flags.append(f"Last rating is {chk.rating_age_days} days old; run with --full for a fresh one.")
    else:
        chk.flags.append("No previous rating for this symbol; run with --full to get one.")
    return chk
