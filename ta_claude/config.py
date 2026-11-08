"""Run configuration: Claude on both tiers, low-variance settings, extra benchmarks."""
from __future__ import annotations

import os
from pathlib import Path

from tradingagents.default_config import build_default_config

HOME = Path(os.getenv("TA_CLAUDE_HOME", Path.home() / ".ta-claude"))

# Use the strongest configured Claude model for both tiers by default. Users can opt into
# a cheaper quick tier explicitly with --quick or TA_QUICK_MODEL.
DEFAULT_DEEP = "claude-opus-5-5"
DEFAULT_QUICK = "claude-opus-5-5"

# Benchmarks the upstream map lacks. Alpha is computed against these.
EXTRA_BENCHMARKS = {
    ".AE": "UAE",       # DFM listings on Yahoo -> iShares MSCI UAE ETF as proxy
    "=X": "DX-Y.NYB",   # spot FX pairs -> US Dollar Index; read raw return alongside alpha
}


def build_config(
    deep: str | None = None,
    quick: str | None = None,
    debate_rounds: int = 1,
    risk_rounds: int = 1,
    temperature: float | None = 0.0,
    effort: str | None = None,
    language: str = "English",
) -> dict:
    cfg = build_default_config()
    cfg.update({
        "llm_provider": "anthropic",
        "deep_think_llm": deep or os.getenv("TA_DEEP_MODEL", DEFAULT_DEEP),
        "quick_think_llm": quick or os.getenv("TA_QUICK_MODEL", DEFAULT_QUICK),
        "max_debate_rounds": debate_rounds,
        "max_risk_discuss_rounds": risk_rounds,
        "temperature": temperature,
        "anthropic_effort": effort,
        "output_language": language,
        "results_dir": str(HOME / "results"),
        "data_cache_dir": str(HOME / "cache"),
        "memory_log_path": str(HOME / "memory" / "trading_memory.md"),
    })
    # Longer suffixes first so "=X" and ".AE" win before the "" default.
    cfg["benchmark_map"] = {**EXTRA_BENCHMARKS, **cfg["benchmark_map"]}
    return cfg
