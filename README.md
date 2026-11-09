# ta-claude

[TradingAgents](https://github.com/TauricResearch/TradingAgents) running on Claude. It adds fixes for the framework's main limitations, and presets for US, Dubai (DFM), India, crypto and FX, plus a live mode that reads the stock page or app you have open.

> Research tool only. Not financial, investment or trading advice.

## No API key needed

Everything works without an API key or paid service. The CLI gathers deterministic data from Yahoo (prices, technical snapshot, plan, FX brief, dated headlines) in seconds. Claude, in the Claude desktop app or Claude Code on your own subscription, then writes the TradingAgents analysis (analysts, bull/bear, trader, risk team, portfolio manager), enriching it only with the connectors you have enabled: **Firecrawl** for full articles and the economic calendar, **Twelve Data** for a live quote, and **Claude in Chrome** or web search as fallbacks.

```bash
ta-claude research EURUSD          # the pack Claude analyses; also what `report` returns without a key
```

## What it fixes

| Upstream limitation | Fix here |
|---|---|
| Two runs of the same ticker and date can differ | `ensemble` runs N times, takes a majority vote and reports the agreement rate (high ≥80%, medium ≥60%, low below that). `temperature=0` is the default. |
| Live news and social feeds drift, so a run can't be reproduced | `report` records every LLM answer **and** every data fetch to SQLite: vendor tools, social feeds, the price snapshot and the company profile. It also snapshots the memory log the prompts read. Re-running the same ticker, date and settings replays it exactly, at no API cost. |
| The model may already know the outcome of past dates (look-ahead) | `backtest` refuses dates on or before the models' training cutoff. Override with `--allow-contaminated`, and the results are flagged. |
| Social feeds leak the future into backtests | Backtests drop the social analyst automatically. |
| No baselines, no costs, no significance test | Backtests report results net of round-trip costs, a bootstrap 95% CI, hit rate, and three baselines: always-long, the benchmark, and random direction. |
| An ensemble would flood the memory log | Ensemble members write to copies of the log. Only the consensus is recorded. |
| Cost | Opus 5.5 is the default for every agent tier for maximum reasoning quality. Select a cheaper analyst tier explicitly with `--quick`. Debate and risk rounds default to 1. Replays are free. |

## Markets

| Market | Example | Pipeline | Alpha benchmark | Point-in-time fundamentals |
|---|---|---|---|---|
| US | `NVDA` | stock, all 4 analysts | SPY | Yes (SEC EDGAR) |
| Dubai (DFM) | `EMAAR.AE` | stock, no social | `UAE` ETF (proxy) | No |
| Abu Dhabi (ADX) | `FAB.AD` | **not on Yahoo**: live mode only | n/a | n/a |
| India | `RELIANCE.NS` | stock, no social | Nifty / Sensex | No |
| Crypto | `BTC-USD` | asset | SPY | n/a |
| FX | `EURUSD`, `GBPJPY=X`, `USDAED` | asset, market + news | US Dollar Index | n/a |

FX pairs get Yahoo's `=X` suffix automatically. Pegged pairs such as USDAED or USDSAR are flagged, because they barely move. Judge FX calls on raw return rather than on alpha.

Before running, check a ticker's classification with `ta-claude market EMAAR.AE,EURUSD`. Yahoo covers DFM stocks under `.AE` (EMAAR.AE was verified, with 5-minute intraday data), but has **no ADX stocks** (FAB and Aldar were checked). ADX tickers are therefore refused by `research` (and the optional paid commands). Live mode still gives a screen-based read for them.

## Use it from Claude Code (easiest)

Open this folder in Claude Code: the Code tab in the Claude desktop app, or `claude` in a terminal here. Then type `/setup`. Claude Code runs the installer, and after that:

| Command | What it does |
|---|---|
| `/analyze NVDA` | Keyless research pack, enriched with your connectors, written up as a TradingAgents rating with a confidence line. |
| `/live` | Reads the stock page or app you have open and checks it against Yahoo. Add `full` for a fresh analysis. |
| `/backtest EURUSD 2025-01-01 2026-01-01` | Strategy track record vs buy-and-hold (`strategy-suite`). |

Plain requests work too. `CLAUDE.md` and the skill tell Claude Code how to handle them. `.claude/settings.json` pre-approves the ta-claude commands and blocks Claude from reading your `.env`.

## Install

macOS or Linux, one step:

```bash
git clone https://github.com/abisinan56-cmyk/tradingagents-claude && cd tradingagents-claude
./setup.sh
```

The script:
1. finds Python 3.11 or newer and creates the environment in `~/.ta-claude/venv`, outside the repo, so iCloud-synced folders stay small;
2. installs ta-claude and runs the offline tests;
3. installs the Claude Code skill to `~/.claude/skills/trading-agents`;
4. puts `ta-claude` on your PATH;
5. creates `.env` for optional settings. No API key is needed.

`ta-claude` reads that `.env` from any folder.

To install by hand instead: `python -m venv .venv && .venv/bin/pip install -e ".[test]" && cp .env.example .env`.

## Use

Every command below is keyless and free.

```bash
# 1. Research pack for one ticker or pair (Claude writes the analysis from it)
ta-claude research NVDA
ta-claude research EURUSD --date 2026-11-03 --json

# 2. Live check of a price read off your screen (seconds)
ta-claude live EMAAR.AE --price 12.30 --source tradingview.com
ta-claude live EMAAR.AE --quote quote.json --full   # plus a fresh research pack

# 3. Deterministic technical model and risk template
ta-claude plan NVDA --rating Buy --json

# 4. Deterministic 20/50 trend-model backtest
ta-claude strategy-backtest NVDA --start 2025-01-01 --end 2026-01-01 --cost-bps 10 --json

# 5. Rank current major-FX research setups, with headlines for the top directional candidate
ta-claude fx-scan --with-news --json

# 6. Structured FX decision-support brief with scenarios, event checklist, portfolio overlap and headlines
ta-claude fx-brief EURUSD --portfolio examples/portfolio.example.json --with-news --json

# 7. Compare four documented signal families under the same costs and execution assumptions
ta-claude strategy-suite EURUSD --start 2025-01-01 --end 2026-01-01 --cost-bps 10 --json
```

`report`, `ensemble` and `backtest` are the original paid multi-agent pipeline. They stay in the code but are not needed: without a key, `report` and `ensemble` return the keyless research pack, and `backtest` points to `strategy-suite`.


## Deterministic trading-model research

`plan` combines completed Yahoo daily closes with an optional TradingAgents rating. Its transparent 20/50-day trend and 20-day momentum rules produce a `long`, `short`, or `flat` research signal, reference entry/stop/target levels, a risk distance of 1.5× ATR-14 (floored at 0.3% and capped at 15% of price; 2× daily close volatility when OHLC is missing) with the target at twice that distance, and a capped model-notional percentage. It writes a portable HTML dashboard to `~/.ta-claude/trade-plans` and never connects to a broker or sends an order.

**The agents see the same numbers.** `report`, `ensemble`, `backtest` and `live --full` run TradingAgents through a thin subclass that appends this deterministic snapshot (regime, last candle, RSI, MACD, ATR, Bollinger, support/resistance, reference levels) to the instrument context every agent reads, so upstream's Trader grounds its entry/stop in the same ATR and levels the CLI reports. The snapshot uses only bars up to the analysis date (safe in backtests), is recorded by replay like other data fetches, and is skipped silently if Yahoo is unavailable. The skill's chat mode follows the same indicator set and risk rule.

**Structured agents use native JSON output.** Upstream's Trader, Research Manager and Portfolio Manager ask for typed output. On Claude Opus 5.5 the library default (forced tool calling) is rejected, which used to cost a second, free-text call per agent; ta-claude switches those calls to Anthropic's `json_schema` structured output, keeping upstream's free-text fallback as a safety net. Recordings made before this change or before the technical snapshot are re-run once rather than replayed.

Use `report --plan` or `ensemble --plan` to attach this independent plan to an LLM research result. The output keeps disagreement explicit rather than resolving it silently. If Yahoo history is unavailable, the completed LLM report still returns and its `trade_plan` field explains why the technical plan was unavailable.

`strategy-suite` compares four intentionally limited daily-bar models: 20/50 trend, Bollinger/RSI mean reversion, 20-bar breakout, and RSI momentum. A signal formed after the close is filled at the following bar's open; positions earn overnight gaps and turnover costs are charged at each change. The simulation uses 100% unlevered notional, has no spread, slippage or financing, and measures drawdown at daily closes. The in-sample comparison cannot identify a future winner.

`fx-brief` turns one pair’s technical plan into a structured decision-support brief: market regime, bullish/bearish and no-trade scenarios, central-bank/inflation/jobs/policy event checklist, transparent conservative/balanced/aggressive risk assumptions, and declared FX portfolio-overlap exposure. It now includes completed daily **OHLC candle analysis** (body/wicks, doji, pin bars, engulfing and inside-bar detection), 20/50-day trend, RSI-14, MACD/signal/histogram, ATR-14, Bollinger bands, and 20-bar support/resistance. Yahoo daily bars newer than 48 hours are conservatively excluded; the latest accepted bar may be older than a trading session and bars older than four calendar days are flagged for review (weekends/holidays can explain the warning). OHLC is adjusted consistently. Portfolio FX legs use signed base units and supplied average price, not current valuation, and are listed separately without netting. The brief does not use a live economic-calendar, bid/ask, liquidity, financing, tax, leverage, or personal-suitability feed; all omissions are returned as warnings. `--with-news` attaches dated Yahoo headlines at no cost; in Claude desktop, the Firecrawl connector adds full articles and this week's calendar.

`fx-scan` ranks the default major pairs (EUR/USD, GBP/USD, USD/JPY, USD/CHF, USD/CAD, AUD/USD and NZD/USD) by the deterministic trend-strength score, with data timestamps, reference risk levels, and data availability warnings. `fx-scan --with-news` then attaches dated Yahoo headlines (with URLs) for the highest-ranked directional candidate at no cost, for Claude to enrich with its connectors. Neither mode claims exhaustive news coverage or treats a rank as an instruction to trade.

`strategy-backtest` simulates the same long/short/flat 20/50 trend rule. A signal uses a completed close and is filled at the following bar open; turnover costs are charged at each position change. Ending positions are marked at the last close without a hypothetical exit cost. The buy-and-hold comparison is measured from the first requested open to the last requested close, before costs. It reports strategy and buy-and-hold returns, drawdown, annualised statistics, and turnover events. It is independent of the LLM training cutoff because it makes no model calls. These outputs are historical research simulations, not investment recommendations or evidence of future performance.

## Look before you risk: time machine, risk check, journal

Three keyless commands adapted from Jake Schincariol's [day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) (MIT), rebuilt for daily bars and both sides of a trade. Nothing here places an order.

```bash
ta-claude timemachine AUDUSD                      # replay the plan's stop/target race from the pair's own bars
ta-claude risk AUDUSD --with-timemachine          # PASS with a size, or BLOCK with every reason
ta-claude risk AUDUSD --with-timemachine --record --note "..."   # journal a plan that passed
ta-claude journal score                           # score finished plans against what really happened
```

**`timemachine`** takes the `plan` for a ticker (entry, 1.5×ATR stop, 2R target) and replays the next 20 trading days 10,000 times, each day drawn at random from the instrument's own last 250 daily bars (open/high/low/close as ratios), checking the stop before the target; a bar that touches both counts as the stop. It also re-runs the same 20/50 rule with the same stop and target on every past day it fired, with real bars. It prints target first %, stop first %, neither %, average R, the history counts and one verdict: *close to a coin flip*, *close to break-even*, *leans toward* or *strongly toward* the target or the stop, judged against the break-even rate for the plan's reward:risk (33% of decided replays at 2R). Seed 19 by default, so the numbers repeat on any machine. It is a simulation built from recent bars, not a prediction: it cannot contain a surprise those bars never saw.

**`risk`** checks the plan against your limits in `~/.ta-claude/risk.json` (copy `examples/risk.example.json`; defaults apply if the file is missing): budget, max loss per trade (1%), daily loss (3%), trades per day (3), reward:risk (≥1.5), position cap (20%), a required stop, a blocked list, no new exposure within 24 hours of a high-impact event (pass the connector's calendar as `--calendar events.json`), and the time-machine verdict. It prints **PASS** with the units that fit and the loss at the stop, or **BLOCK** with every reason. A PASS is a rules check, not a recommendation, and the skill never loosens a limit to pass a plan.

**`journal`** keeps every plan you recorded in `~/.ta-claude/journal.jsonl`; `journal score` later checks each finished one against the real bars that followed and summarises target-first, stop-first and average R. Under 30 scored entries it says the sample is too small to call the rule an edge.

On 9 Nov 2026 the first live run blocked `fx-scan`'s own top candidate: AUD/USD short replayed stop-first 68% vs target-first 25%, and the rule's real history on the pair was 257 stops to 62 targets.

## Free data sources (evaluated, not integrated in code)

The CLI uses Yahoo only (no key). Richer data comes through the connectors in your Claude desktop app (Firecrawl, Twelve Data, Claude in Chrome), never through API keys in this repo. The table below records free sources checked in November 2026, for reference only; free tiers change.

| Source | Free tier | Would improve | Notes |
|---|---|---|---|
| ForexFactory weekly calendar JSON (`nfs.faireconomy.media/ff_calendar_thisweek.json`) | No key | Real upcoming high-impact events per currency, replacing the static event checklist | Unofficial feed, no uptime guarantee; cache and poll sparingly |
| OANDA v20 practice (demo) account | Free account and token | Bid/ask, intraday candles and an explicit `complete` flag per candle, replacing the 48-hour delay | Not offered by every OANDA entity; use read-only pricing and candle endpoints only |
| Twelve Data Basic | 800 credits/day, 8/minute | Intraday FX candles for the major pairs | Free key |
| Frankfurter (`api.frankfurter.dev`) | No key | Daily central-bank reference rate to cross-check Yahoo | No candles or spreads; not trading data |
| Alpha Vantage | 25 requests/day | — | Too small for regular scans |
| Finnhub | Free key, ~60 calls/minute | Economic calendar and FX candles are advertised | Whether these are on the free plan was not confirmed |

This repo stays keyless: use these through Claude desktop connectors where one exists, keep Yahoo as the base, and never place orders.

## Live mode

The agents only see Yahoo's data feed, which can lag your screen: DFM and many other non-US venues are delayed. `ta-claude live` takes the price from your screen and reports:
- how far the screen price is from Yahoo's latest bar;
- how many minutes Yahoo lags;
- the session move;
- the last rating and how old it is.

`--full` adds a fresh multi-agent run.

With the skill installed, ask Claude for a live update while a stock page (TradingView, Yahoo, Investing, DFM/ADX, NSE, Binance, a broker web platform) or a desktop trading app is open. Claude then:
1. reads the price off the page or app, read-only (it never clicks trade buttons);
2. runs the check;
3. tells you whether the rating rests on delayed data.

Say "update" to repeat it.

Common flags:
- `--deep` / `--quick`: models per tier
- `--debate-rounds` / `--risk-rounds`
- `--effort low|medium|high`
- `--analysts market,news`
- `--json`: machine-readable output

Results, replay files and the memory log are stored in `~/.ta-claude`. Set `TA_CLAUDE_HOME` to change that location.

## Cost guide

The keyless commands cost nothing. Connector use is the only limit: free Firecrawl and Twelve Data quotas are small, so the skill uses about 2–3 scrapes and one quote per analysis and falls back to Claude in Chrome or web search when a quota runs out.

## Limits that remain

- **Ensembles reduce variance; they don't remove it.** Low agreement is itself a signal: it means the call is unclear.
- **Replay freezes a run; it doesn't make the first run any more correct.**
- **Few clean backtest dates are available.** Anything after the cutoff is only months old, so samples are small, and the report says when they are too small to conclude anything.
- **Model cutoffs need maintaining.** `ta_claude/cutoff.py` knows Opus 5.5 (2026-06-30). Other Claude models are held to that date as a conservative bound. For a newer model, set `TA_MODEL_CUTOFF` or edit the table.
- **The UAE benchmark is a US-listed ETF proxy, and UAE and India fundamentals are withheld on past dates.** Backtests for those markets rely on price and news only.
- **ADX stocks have no Yahoo data.** Only live mode, which reads the screen, works for them.
- **"Live" means live price, not live reasoning.** A full multi-agent run takes several minutes, and it analyses Yahoo's feed, which may be delayed. Live mode reports that gap rather than hiding it.
- **Replay settles due decisions against current prices.** Settling past decisions fetches prices live, so a replay of a run whose snapshot holds unsettled decisions can still make a fresh price call.

## Claude skill

`skill/trading-agents/SKILL.md` lets Claude run this project for you from plain requests.
- **Claude desktop / Claude Code:** keyless CLI mode. It runs `ta-claude research`, enriches the pack with your connectors (Firecrawl, Twelve Data, Claude in Chrome), writes the TradingAgents roles, and reads your open stock pages for live mode.
- **claude.ai (no shell):** fast chat mode. Claude runs the TradingAgents roles itself: prices and indicators come from Yahoo through Claude in Chrome in one batched call, and news comes from web search. There are no screenshots, about 4 tool calls in all, and the result is labelled as single-model.

To install in Claude Code, copy the folder to `~/.claude/skills/trading-agents/`. On claude.ai, upload the zipped folder under Settings → Capabilities → Skills.

## Upstream

This project is pinned to TradingAgents commit `9fa1196` (Apache-2.0). Bump the pin in `pyproject.toml` deliberately, then re-run `pytest`. The time machine, risk check and journal are adapted from [day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) by Jake Schincariol (MIT).
