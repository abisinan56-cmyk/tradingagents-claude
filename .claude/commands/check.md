---
description: Look before you risk — replay a plan 10,000 times, then PASS/BLOCK it against my limits (e.g. /check AUDUSD)
argument-hint: <ticker>
---
Check $ARGUMENTS with the trading-agents skill, section 2.6:
1. Run `ta-claude timemachine <T> --json` and read back the odds, the history counts, the verdict word for word and the seed.
2. Run `ta-claude risk <T> --with-timemachine --json` (add `--calendar events.json` if you fetched this week's high-impact events with a connector). Report PASS with the size, or BLOCK with every reason.
3. Never loosen a limit to pass it. If I say "journal it", re-run risk with `--record --note "<my note>"`.
4. End with: a simulation and a rules check, not a prediction or advice.
