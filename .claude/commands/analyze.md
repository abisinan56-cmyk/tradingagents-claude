---
description: TradingAgents rating for a ticker or FX pair (e.g. /analyze NVDA, /analyze EURUSD ensemble)
argument-hint: <ticker> [ensemble]
---
Analyse $ARGUMENTS with the trading-agents skill:
- If the arguments include "ensemble", run `ta-claude ensemble <T> -n 5 --json`.
- Otherwise run `ta-claude report <T> --json`.

Run it in the background, and reply in the skill's short report format.
