"""Trade journal: write down every plan you act on, then score it against what happened.

Entries are JSON lines in ``~/.ta-claude/journal.jsonl``. A scored entry records which
of stop or target was touched first (stop wins a tie), or the R at the end of the
holding window, using real daily bars after the entry date. Fewer than 30 scored
entries is too few to call the rule an edge; the summary says so.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .config import HOME

JOURNAL = HOME / "journal.jsonl"


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _save(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")


def record(plan: dict, verdict: dict | None = None, note: str = "", path: Path = JOURNAL,
           units: float | None = None, now: datetime | None = None) -> dict:
    """Append a plan (and its risk verdict) to the journal; returns the entry."""
    now = now or datetime.now(timezone.utc)
    entry = {"id": now.strftime("%Y%m%dT%H%M%SZ") + "-" + plan["ticker"].replace("=X", ""),
             "recorded_at": now.isoformat(), "date": now.date().isoformat(), "ticker": plan["ticker"],
             "action": plan["action"], "as_of": plan["as_of"], "entry": plan["entry_reference"],
             "stop": plan.get("stop_reference"), "target": plan.get("target_reference"),
             "horizon_days": 20, "units": units,
             "max_loss_at_stop": (verdict or {}).get("max_loss_at_stop"),
             "risk": (verdict or {}).get("status"), "note": note, "outcome": None}
    entries = _load(path)
    entries.append(entry)
    _save(path, entries)
    return entry


def today_entries(path: Path = JOURNAL, today: date | None = None) -> list[dict]:
    today = (today or datetime.now(timezone.utc).date()).isoformat()
    return [e for e in _load(path) if e.get("date") == today]


def score(path: Path = JOURNAL, fetch=None) -> dict:
    """Score unscored directional entries whose window has closed; returns a summary."""
    from .model import fetch_daily_history
    fetch = fetch or fetch_daily_history
    entries = _load(path)
    scored_now = 0
    for e in entries:
        if e.get("outcome") or e.get("action") not in ("long", "short") or e.get("stop") is None:
            continue
        start = date.fromisoformat(e["as_of"])
        end = start + timedelta(days=e.get("horizon_days", 20) * 2)  # calendar days for ~20 trading days
        try:
            bars = fetch(e["ticker"], start.isoformat(), end.isoformat())
        except ValueError:
            continue
        future = [b for b in bars if b.day > e["as_of"]][:e.get("horizon_days", 20)]
        if len(future) < e.get("horizon_days", 20):
            continue  # window not finished yet
        direction = 1 if e["action"] == "long" else -1
        risk = abs(e["entry"] - e["stop"])
        outcome, r = "neither", direction * (future[-1].close - e["entry"]) / risk
        for b in future:
            high, low = b.high or b.close, b.low or b.close
            if (low <= e["stop"]) if direction > 0 else (high >= e["stop"]):
                outcome, r = "stop", -1.0
                break
            if e.get("target") is not None and ((high >= e["target"]) if direction > 0 else (low <= e["target"])):
                outcome, r = "target", abs(e["target"] - e["entry"]) / risk
                break
        e["outcome"], e["r"], e["scored_at"] = outcome, round(r, 3), datetime.now(timezone.utc).isoformat()
        scored_now += 1
    _save(path, entries)
    return summary(entries, scored_now)


def summary(entries: list[dict], scored_now: int = 0) -> dict:
    done = [e for e in entries if e.get("outcome")]
    wins = sum(e["outcome"] == "target" for e in done)
    losses = sum(e["outcome"] == "stop" for e in done)
    rs = [e["r"] for e in done]
    out = {"entries": len(entries), "scored": len(done), "scored_now": scored_now, "target_first": wins,
           "stop_first": losses, "neither": len(done) - wins - losses,
           "average_r": round(sum(rs) / len(rs), 3) if rs else None,
           "open": [e["id"] for e in entries if not e.get("outcome")]}
    if len(done) < 30:
        out["note"] = f"{len(done)} scored entries is too few to call this an edge; judge after 30 or more."
    return out
