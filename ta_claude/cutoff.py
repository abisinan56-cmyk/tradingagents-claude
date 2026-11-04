"""Training-data look-ahead guard for backtests.

An LLM asked about a date before its training cutoff may already know what the
price did next. A backtest on such dates measures memory, not judgement, so
every backtest date must fall after the latest cutoff of the models in use.
"""
from __future__ import annotations

import os
from datetime import date

# Reliable knowledge cutoffs. Edit this table, or set TA_MODEL_CUTOFF=YYYY-MM-DD
# to override for every model.
KNOWN_CUTOFFS = {
    "claude-opus-5-5": date(2026, 6, 30),
}

# Unknown Claude 5-family or earlier models were released no later than Opus 5.5,
# so its cutoff is a safe upper bound for them. Anything else must be set by hand.
CONSERVATIVE_CLAUDE_BOUND = date(2026, 6, 30)


class CutoffError(ValueError):
    pass


def model_cutoff(model: str) -> tuple[date, bool]:
    """Return (cutoff, exact). exact=False means the conservative bound was used."""
    override = os.getenv("TA_MODEL_CUTOFF")
    if override:
        return date.fromisoformat(override), True
    if model in KNOWN_CUTOFFS:
        return KNOWN_CUTOFFS[model], True
    if model.startswith("claude-"):
        return CONSERVATIVE_CLAUDE_BOUND, False
    raise CutoffError(
        f"No training cutoff known for {model!r}. Add it to KNOWN_CUTOFFS in "
        "ta_claude/cutoff.py or set TA_MODEL_CUTOFF=YYYY-MM-DD."
    )


def check_dates(dates: list[str], models: list[str], allow_contaminated: bool = False) -> list[str]:
    """Raise if any date is on or before the latest model cutoff. Returns notes."""
    cutoffs = [(m, *model_cutoff(m)) for m in dict.fromkeys(models)]
    latest = max(c for _, c, _ in cutoffs)
    notes = [f"{m}: cutoff {c}{'' if exact else ' (conservative bound)'}" for m, c, exact in cutoffs]
    bad = [d for d in dates if date.fromisoformat(d) <= latest]
    if bad and not allow_contaminated:
        raise CutoffError(
            f"{len(bad)} backtest date(s) fall on or before the model cutoff {latest} "
            f"(first: {bad[0]}). The model may already know these outcomes. Start the "
            f"grid after {latest}, or pass --allow-contaminated to run anyway (results flagged)."
        )
    if bad:
        notes.append(f"WARNING: {len(bad)} date(s) are before the cutoff; results are contaminated.")
    return notes
