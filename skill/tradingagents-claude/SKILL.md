---
name: tradingagents-claude
description: Run the ta-claude project (TradingAgents multi-agent analysis on Claude) for a stock, UAE/India listing, crypto or FX pair - a single report, an ensemble vote with confidence, a look-ahead-safe backtest, or a portfolio-aware run. Use when the user asks to analyse a ticker or currency pair with TradingAgents, get a buy/sell rating, test the agents' track record, or check a holding against their portfolio.
---

# TradingAgents on Claude

This skill drives the `ta-claude` CLI from this repository. Its output is research only, never advice. Say so once in the final answer.

## 0. Preconditions (check silently)
- Run `ta-claude --help`. If the command is missing, `cd` to the repo and run `pip install -e .`.
- `ANTHROPIC_API_KEY` must be set (in `.env` or the environment). If it is not, ask the user to add it to `.env`. Never ask for the key in chat, and never write it anywhere.

## 1. Pick the job

| User wants | Command |
|---|---|
| A view on one ticker or pair today or on a date | `ta-claude report <T> [--date YYYY-MM-DD]` |
| A more reliable call, or "how sure is it" | `ta-claude ensemble <T> -n 5` |
| "Does it work", or a track record | `ta-claude backtest <T1,T2> --start ... --end ... --every 7` |
| A view on something they hold | add `--portfolio <file.json>` to any of the above |

If the market is unclear, run `ta-claude market <T>` first. It is free.

Ticker forms:
- US: `NVDA`
- UAE: `EMAAR.AE` (confirm it on finance.yahoo.com)
- India: `RELIANCE.NS`
- Crypto: `BTC-USD`
- FX: `EURUSD` (becomes `EURUSD=X`)

## 2. Guardrails before spending money
- **Cost:** a backtest costs about (tickers × dates) times a single report, and an ensemble costs about N times a single report. Before any backtest over 10 cells, or any ensemble with n over 5, state the cell count and get a yes.
- **Backtest dates:** every date must fall after the model cutoff, 2026-06-30 for the default models. If the user asks for earlier dates, explain the look-ahead problem. Use `--allow-contaminated` only if they insist, and label the results contaminated.
- **Portfolio JSON:** the shape is `{"cash": 0, "currency": "USD", "positions": [{"ticker": "...", "quantity": 0, "average_price": 0}]}`. If the user describes their holdings in words, write the file, show it, and confirm it before running. An empty `positions` list means a flat book, which is not the same as passing no file.
- **FX pegged pairs** (USDAED, USDSAR and similar): warn that signals will be noise before running.

## 3. Run
- Add `--json` and parse the output.
- Runs take minutes. Use a background command, and do not re-launch a run that is already in progress.
- `report` records and replays automatically. Re-running the same ticker, date and models is free and identical. Use `--no-replay` for a fresh sample.

## 4. Report back (short)
- **report:** the rating, a 3-line summary taken from the saved report's final decision, the path to `complete_report.html`, and any market notes.
- **ensemble:** the rating, the agreement percentage and confidence, and the vote split. If confidence is low, say the call is not clear rather than presenting the rating as firm.
- **backtest:**
  1. Scored count first.
  2. Net mean per decision with its CI. If the CI spans zero, say there is no evidence of an edge.
  3. Hit rate.
  4. Baselines (always-long, benchmark, random).
  5. Every note, including the cutoff and the small-sample warnings.
  Never describe a backtest as profitable without comparing it to the baselines.
- Close with the research-only disclaimer.

## Install this skill
- **Claude Code:** copy this folder to `~/.claude/skills/tradingagents-claude/`.
- **claude.ai:** zip this folder and upload it under Settings → Capabilities → Skills.
