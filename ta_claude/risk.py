"""Rules-based risk check for a plan: PASS or BLOCK with the reason, before anyone acts.

Adapted from the day-trader-skill Risk Manager (MIT, Jake Schincariol) to this
project's plans: no orders, no broker, no execution. It reads the plan, the user's
limits (``risk.json``) and the journal of what was already taken today, and says
whether the plan fits the limits. A PASS is a rules check, not a recommendation.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from .config import HOME

DEFAULT_LIMITS = {
    "account_currency": "USD",
    "budget": 5000,
    "max_loss_per_trade_pct": 1.0,
    "max_daily_loss_pct": 3.0,
    "max_trades_per_day": 3,
    "min_reward_risk": 1.5,
    "max_position_pct": 20,
    "require_stop": True,
    "no_new_exposure_hours_before_high_impact_event": 24,
    "blocked": [],
    "require_time_machine_lean": False,
}

RISK_FILE = HOME / "risk.json"


@dataclass
class RiskVerdict:
    ticker: str
    as_of: str
    passed: bool
    reasons: list[str]
    warnings: list[str] = field(default_factory=list)
    position_units: float | None = None
    max_loss_at_stop: float | None = None
    limits_used: dict = field(default_factory=dict)

    @property
    def status(self) -> str:
        return "PASS" if self.passed else "BLOCK"


def load_limits(path: str | Path | None = None) -> dict:
    """User limits merged over the defaults; the file is optional."""
    limits = dict(DEFAULT_LIMITS)
    target = Path(path) if path else RISK_FILE
    if target.exists():
        try:
            user = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Could not read limits {target}: {exc}") from exc
        if not isinstance(user, dict):
            raise ValueError(f"Limits file {target} must be a JSON object.")
        limits.update(user)
    for key in ("budget", "max_loss_per_trade_pct", "max_daily_loss_pct", "min_reward_risk", "max_position_pct"):
        value = limits[key]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"Limit {key!r} must be a positive number.")
    return limits


def check_plan(plan: dict, limits: dict, journal_today: list[dict] | None = None,
               calendar: list[dict] | None = None, time_machine: dict | None = None,
               today: date | None = None) -> RiskVerdict:
    """Check one plan (from ``build_trade_plan``) against the limits.

    ``journal_today`` holds today's journal entries (for trades per day and daily loss).
    ``calendar`` holds upcoming high-impact events with ``hours_away``; ``time_machine``
    is the TimeMachine dict when the user ran it.
    """
    reasons: list[str] = []
    warnings: list[str] = []
    ticker, action = plan["ticker"], plan["action"]
    entry, stop, target = plan["entry_reference"], plan.get("stop_reference"), plan.get("target_reference")
    today = today or datetime.now(timezone.utc).date()
    journal_today = journal_today or []

    if ticker in limits.get("blocked", []):
        reasons.append(f"{ticker} is on your blocked list.")
    if action == "flat":
        reasons.append("The plan is flat: no entry, so there is nothing to size. Wait for a directional regime.")
        return RiskVerdict(ticker, plan["as_of"], False, reasons, warnings, limits_used=limits)
    if limits["require_stop"] and stop is None:
        reasons.append("No stop in the plan and require_stop is on.")
        return RiskVerdict(ticker, plan["as_of"], False, reasons, warnings, limits_used=limits)

    direction = 1 if action == "long" else -1
    if direction * (entry - stop) <= 0:
        reasons.append("The stop is on the wrong side of the entry.")
    if target is not None and direction * (target - entry) <= 0:
        reasons.append("The target is on the wrong side of the entry.")
    risk_per_unit = abs(entry - stop)
    reward_risk = abs(target - entry) / risk_per_unit if target is not None and risk_per_unit else None
    if reward_risk is not None and reward_risk < limits["min_reward_risk"]:
        reasons.append(f"Reward:risk {reward_risk:.2f} is under your minimum {limits['min_reward_risk']}.")

    budget = limits["budget"]
    max_loss = budget * limits["max_loss_per_trade_pct"] / 100
    units = math.floor(max_loss / risk_per_unit) if risk_per_unit else 0
    notional = units * entry
    cap = budget * limits["max_position_pct"] / 100
    if notional > cap:
        units = math.floor(cap / entry)
        notional = units * entry
        warnings.append(f"Size cut to the {limits['max_position_pct']}% position cap ({units} units).")
    if units <= 0:
        reasons.append(f"Max loss {max_loss:.2f} {limits['account_currency']} buys 0 units at risk "
                       f"{risk_per_unit:.5g} per unit; the stop is too wide for your budget.")
    loss_at_stop = units * risk_per_unit

    taken = [e for e in journal_today if e.get("action") in ("long", "short")]
    if len(taken) >= limits["max_trades_per_day"]:
        reasons.append(f"{len(taken)} trades already journaled today; your limit is {limits['max_trades_per_day']}.")
    daily_cap = budget * limits["max_daily_loss_pct"] / 100
    committed = sum(e.get("max_loss_at_stop") or 0 for e in taken)
    if committed + loss_at_stop > daily_cap:
        reasons.append(f"Daily risk {committed + loss_at_stop:.2f} would exceed your daily loss limit {daily_cap:.2f}.")

    window = limits["no_new_exposure_hours_before_high_impact_event"]
    soon = [e for e in (calendar or []) if e.get("hours_away") is not None and 0 <= e["hours_away"] <= window]
    if soon:
        first = soon[0]
        reasons.append(f"High-impact {first.get('currency')} event in {first['hours_away']:.0f}h: "
                       f"{first.get('title')}. No new exposure inside {window}h of it.")

    if time_machine:
        verdict = time_machine.get("verdict", "")
        if "toward the stop" in verdict:
            reasons.append(f"Time machine leans toward the stop: {verdict}")
        elif limits["require_time_machine_lean"] and "toward the target" not in verdict:
            reasons.append(f"Time machine does not lean toward the target: {verdict}")
        elif "coin flip" in verdict or "break-even" in verdict:
            warnings.append(f"Time machine: {verdict}")
    elif limits["require_time_machine_lean"]:
        reasons.append("require_time_machine_lean is on and the time machine was not run.")

    age = (today - date.fromisoformat(plan["as_of"])).days
    if age > 4:
        warnings.append(f"Plan data is {age} days old; re-run before relying on the levels.")
    for w in plan.get("warnings", []):
        if "disagree" in w:
            warnings.append(w)

    return RiskVerdict(ticker, plan["as_of"], not reasons, reasons, warnings,
                       units if not reasons else None, round(loss_at_stop, 2) if not reasons else None, limits)
