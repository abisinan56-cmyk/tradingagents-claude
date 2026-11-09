---
description: TradingAgents rating for a ticker or FX pair, no API key (e.g. /analyze NVDA, /analyze EURUSD)
argument-hint: <ticker>
---
Analyse $ARGUMENTS with the trading-agents skill, keyless mode (section 0):
1. Run `ta-claude research <T> --json`.
2. Enrich it with the connectors this session has, following `connector_steps`: Firecrawl for 2-3 headline articles and this week's high-impact calendar events, Twelve Data for one live quote. Skip any that are not connected and say so.
3. Write the TradingAgents analysis from the pack, following `analysis_steps`, including a confidence line, and reply in the skill's short report format.
