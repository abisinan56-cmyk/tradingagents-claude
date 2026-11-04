---
description: Look-ahead-safe backtest (e.g. /backtest NVDA,EURUSD 2026-07-06 2026-10-26)
argument-hint: <tickers> <start> <end> [every-days]
---
Backtest with the trading-agents skill: $ARGUMENTS
1. Every date must be after 2026-06-30.
2. Work out the cell count (tickers × dates), state the cost, and wait for my yes if it is over 10.
3. Run `ta-claude backtest ... --json` in the background.
4. Report in this order: scored count, net mean with its CI, hit rate, baselines, then all notes.
