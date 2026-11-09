---
description: Live read of the stock/FX page or trading app I have open, checked against Yahoo
argument-hint: [ticker] [full]
---
Do a live update following section 2 of the trading-agents skill. Optional ticker and "full": $ARGUMENTS
- Find my open stock page or app, and read the price, read-only.
- Write `quote.json` with both `captured_at` (the time you read it) and `screen_time` (the page's own timestamp).
- Run `ta-claude live <T> --quote quote.json --json`.
- Run a fresh analysis (`--full`, keyless research pack) only if I wrote "full", or if there is no rating; then write the analysis from it as in skill section 0.
