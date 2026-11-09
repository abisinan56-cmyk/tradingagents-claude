"""Time Machine for a plan: replay the stop/target race from the instrument's own bars.

Adapted from the day-trader-skill Time Machine (MIT, Jake Schincariol) to daily bars
and to both sides. A replay draws each future day from the instrument's own recent
daily bars (open/high/low/close as ratios to the prior close) and walks the plan's
holding window, checking the stop before the target; a bar that touches both counts
as the stop. The history re-runs the same 20/50 rule and the same stop/target on every
past day it fired, with real bars. The verdict compares target-first odds with the
break-even rate for the plan's reward:risk. A simulation, never a prediction.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from statistics import fmean

from .model import PriceBar, _atr_pct, _signal

DEFAULT_SEED = 19


@dataclass
class TimeMachine:
    ticker: str
    as_of: str
    action: str
    entry: float
    stop: float
    target: float
    reward_risk: float
    horizon_days: int
    replays: int
    seed: int
    pool_days: int
    target_first_pct: float
    stop_first_pct: float
    neither_pct: float
    average_r: float
    close_r_percentiles: dict[str, float]
    history: dict
    verdict: str
    notes: list[str] = field(default_factory=list)


def _ratios(bars: list[PriceBar]) -> list[tuple[float, float, float, float]]:
    out = []
    for prior, bar in zip(bars[:-1], bars[1:]):
        if None in (bar.open, bar.high, bar.low) or prior.close <= 0:
            continue
        out.append((bar.open / prior.close, bar.high / prior.close, bar.low / prior.close, bar.close / prior.close))
    return out


def _walk(path: list[tuple[float, float, float, float]], entry: float, stop: float, target: float,
          direction: int) -> tuple[str, float]:
    """Return (outcome, R) for one path of (open, high, low, close) ratios from the entry."""
    price = entry
    risk = abs(entry - stop)
    for o, h, lo, c in path:
        high, low = price * h, price * lo
        hit_stop = low <= stop if direction > 0 else high >= stop
        hit_target = high >= target if direction > 0 else low <= target
        if hit_stop:  # stop first when both touch
            return "stop", -1.0
        if hit_target:
            return "target", abs(target - entry) / risk
        price = price * c
    return "neither", direction * (price - entry) / risk


def _history(bars: list[PriceBar], horizon: int, reward_risk: float) -> dict:
    """Re-run the 20/50 rule with the same ATR stop and R target on every past day it fired."""
    fired = wins = losses = neither = 0
    for i in range(51, len(bars) - 1):
        closes = [b.close for b in bars[:i + 1]]
        action, *_ = _signal(closes)
        if action == "flat":
            continue
        atr = _atr_pct(bars[:i + 1])
        if not atr:
            continue
        direction = 1 if action == "long" else -1
        entry = bars[i].close
        stop_pct = min(0.15, max(0.003, 1.5 * atr))
        stop = entry * (1 - direction * stop_pct)
        target = entry * (1 + direction * stop_pct * reward_risk)
        future = bars[i + 1:i + 1 + horizon]
        path = [(b.open / prior.close, b.high / prior.close, b.low / prior.close, b.close / prior.close)
                for prior, b in zip([bars[i], *future[:-1]], future) if None not in (b.open, b.high, b.low)]
        if len(path) < horizon:
            continue  # needs the full window to be scored
        outcome, _ = _walk(path, entry, stop, target, direction)
        fired += 1
        wins += outcome == "target"
        losses += outcome == "stop"
        neither += outcome == "neither"
    return {"fired": fired, "target_first": wins, "stop_first": losses, "neither": neither,
            "note": "Real past bars, same rule, same stop and target; signals that fired after the "
                    "bar before the entry are excluded so nothing after the entry is used."}


def verdict_line(target_pct: float, stop_pct: float, reward_risk: float) -> str:
    decided = target_pct + stop_pct
    if decided <= 0:
        return "No replay reached the stop or the target inside the window."
    share = target_pct / decided * 100
    break_even = 100 / (1 + reward_risk)
    gap = share - break_even
    if abs(gap) < 5:
        return ("Close to a coin flip" if abs(reward_risk - 1) < 1e-9 else "Close to break-even") + \
               f": target first {target_pct:.1f}% vs stop first {stop_pct:.1f}% (needs {break_even:.0f}% of decided replays, got {share:.0f}%)."
    lean = "target" if gap > 0 else "stop"
    strength = "Strongly toward" if abs(gap) >= 15 else "Leans toward"
    return f"{strength} the {lean}: target first {target_pct:.1f}% vs stop first {stop_pct:.1f}% (break-even {break_even:.0f}%, got {share:.0f}%)."


def run_time_machine(ticker: str, bars: list[PriceBar], entry: float, stop: float, target: float, action: str,
                     horizon_days: int = 20, replays: int = 10_000, seed: int = DEFAULT_SEED,
                     pool_days: int = 250) -> TimeMachine:
    """Replay the plan from the last ``pool_days`` of daily bars before ``bars[-1]``."""
    if action not in ("long", "short"):
        raise ValueError("The time machine needs a long or short plan; a flat plan has no stop or target.")
    direction = 1 if action == "long" else -1
    if direction * (entry - stop) <= 0 or direction * (target - entry) <= 0:
        raise ValueError("Stop must be on the losing side of the entry and target on the winning side.")
    pool = _ratios(bars[-pool_days - 1:])
    if len(pool) < 60:
        raise ValueError(f"Need at least 60 complete daily bars with OHLC for the replay pool; got {len(pool)}.")
    rng = random.Random(seed)
    counts = {"target": 0, "stop": 0, "neither": 0}
    rs = []
    for _ in range(replays):
        path = [pool[rng.randrange(len(pool))] for _ in range(horizon_days)]
        outcome, r = _walk(path, entry, stop, target, direction)
        counts[outcome] += 1
        rs.append(r)
    rs.sort()
    pct = lambda p: round(rs[min(len(rs) - 1, int(p * len(rs)))], 2)  # noqa: E731
    reward_risk = round(abs(target - entry) / abs(entry - stop), 2)
    t_pct, s_pct, n_pct = (round(counts[k] / replays * 100, 1) for k in ("target", "stop", "neither"))
    notes = ["Each replay day is drawn at random from the instrument's own recent daily bars; it cannot "
             "contain an event those bars never saw (a central-bank surprise, a gap, a halt).",
             "A gap through the stop counts as exactly -1R here; a real fill can be worse.",
             "Same plan, same data, same seed give the same numbers on any machine."]
    if n_pct > 40:
        notes.append(f"{n_pct:.0f}% of replays were still open after {horizon_days} days; their R is the "
                     "distance from the entry at that point, so the window matters.")
    return TimeMachine(ticker, bars[-1].day, action, entry, stop, target, reward_risk, horizon_days, replays,
                       seed, len(pool), t_pct, s_pct, n_pct, round(fmean(rs), 3),
                       {"p10": pct(0.10), "p50": pct(0.50), "p90": pct(0.90)},
                       _history(bars, horizon_days, reward_risk), verdict_line(t_pct, s_pct, reward_risk), notes)
