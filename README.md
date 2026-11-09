# ta-claude

[TradingAgents](https://github.com/TauricResearch/TradingAgents) running on Claude. It adds fixes for the framework's main limitations, and presets for US, Dubai (DFM), India, crypto and FX, plus a live mode that reads the stock page or app you have open.

> Research tool only. Not financial, investment or trading advice.

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

Before running, check a ticker's classification with `ta-claude market EMAAR.AE,EURUSD`. Yahoo covers DFM stocks under `.AE` (EMAAR.AE was verified, with 5-minute intraday data), but has **no ADX stocks** (FAB and Aldar were checked). ADX tickers are therefore refused by `report`, `ensemble` and `backtest`. Live mode still gives a screen-based read for them.

## Use it from Claude Code (easiest)

Open this folder in Claude Code: the Code tab in the Claude desktop app, or `claude` in a terminal here. Then type `/setup`. Claude Code runs the installer, and after that:

| Command | What it does |
|---|---|
| `/analyze NVDA` | Rating for a ticker or pair. Add `ensemble` for a vote with confidence. |
| `/live` | Reads the stock page or app you have open and checks it against Yahoo. Add `full` for a fresh analysis. |
| `/backtest NVDA,EURUSD 2026-07-06 2026-10-26` | Look-ahead-safe backtest. |

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
5. creates `.env`, where you paste your `ANTHROPIC_API_KEY`.

`ta-claude` reads that `.env` from any folder.

To install by hand instead: `python -m venv .venv && .venv/bin/pip install -e ".[test]" && cp .env.example .env`.

## Use

```bash
# 1. Single report (recorded; re-running replays it exactly)
ta-claude report NVDA --date 2026-11-03

# 2. Ensemble with confidence
ta-claude ensemble EMAAR.AE -n 5

# 3. Backtest (dates must be after the model cutoff, 2026-06-30)
ta-claude backtest NVDA,RELIANCE.NS,EURUSD --start 2026-07-06 --end 2026-10-26 --every 7 --cost-bps 10

# 4. Portfolio-aware (works with report, ensemble or backtest)
ta-claude report NVDA --portfolio examples/portfolio.example.json

# 5. Live check of a price read off your screen (seconds, no API cost)
ta-claude live EMAAR.AE --price 12.30 --source tradingview.com
ta-claude live EMAAR.AE --quote quote.json --full   # plus a fresh analysis (minutes, costs API)

# 6. Deterministic technical model and risk template (no LLM/API key)
ta-claude plan NVDA --rating Buy --json

# 7. Deterministic 20/50 trend-model backtest (no LLM/API key)
ta-claude strategy-backtest NVDA --start 2025-01-01 --end 2026-01-01 --cost-bps 10 --json

# 8. Rank current major-FX research setups; fresh news research for its top directional candidate costs API usage
ta-claude fx-scan --json
ta-claude fx-scan --with-news --json

# 9. Structured FX decision-support brief with scenarios, risks, event checklist, and portfolio overlap
ta-claude fx-brief EURUSD --portfolio examples/portfolio.example.json --json
ta-claude fx-brief EURUSD --with-news --json  # fresh market/news research costs API usage

# 10. Compare four documented signal families under the same costs and execution assumptions
ta-claude strategy-suite EURUSD --start 2025-01-01 --end 2026-01-01 --cost-bps 10 --json
```


## Deterministic trading-model research

`plan` combines completed Yahoo daily closes with an optional TradingAgents rating. Its transparent 20/50-day trend and 20-day momentum rules produce a `long`, `short`, or `flat` research signal, reference entry/stop/target levels, a risk distance of 1.5× ATR-14 (floored at 0.3% and capped at 15% of price; 2× daily close volatility when OHLC is missing) with the target at twice that distance, and a capped model-notional percentage. It writes a portable HTML dashboard to `~/.ta-claude/trade-plans` and never connects to a broker or sends an order.

**The agents see the same numbers.** `report`, `ensemble`, `backtest` and `live --full` run TradingAgents through a thin subclass that appends this deterministic snapshot (regime, last candle, RSI, MACD, ATR, Bollinger, support/resistance, reference levels) to the instrument context every agent reads, so upstream's Trader grounds its entry/stop in the same ATR and levels the CLI reports. The snapshot uses only bars up to the analysis date (safe in backtests), is recorded by replay like other data fetches, and is skipped silently if Yahoo is unavailable. The skill's chat mode follows the same indicator set and risk rule.

**Structured agents use native JSON output.** Upstream's Trader, Research Manager and Portfolio Manager ask for typed output. On Claude Opus 5.5 the library default (forced tool calling) is rejected, which used to cost a second, free-text call per agent; ta-claude switches those calls to Anthropic's `json_schema` structured output, keeping upstream's free-text fallback as a safety net. Recordings made before this change or before the technical snapshot are re-run once rather than replayed.

Use `report --plan` or `ensemble --plan` to attach this independent plan to an LLM research result. The output keeps disagreement explicit rather than resolving it silently. If Yahoo history is unavailable, the completed LLM report still returns and its `trade_plan` field explains why the technical plan was unavailable.

`strategy-suite` compares four intentionally limited daily-bar models: 20/50 trend, Bollinger/RSI mean reversion, 20-bar breakout, and RSI momentum. A signal formed after the close is filled at the following bar's open; positions earn overnight gaps and turnover costs are charged at each change. The simulation uses 100% unlevered notional, has no spread, slippage or financing, and measures drawdown at daily closes. The in-sample comparison cannot identify a future winner.

`fx-brief` turns one pair’s technical plan into a structured decision-support brief: market regime, bullish/bearish and no-trade scenarios, central-bank/inflation/jobs/policy event checklist, transparent conservative/balanced/aggressive risk assumptions, and declared FX portfolio-overlap exposure. It now includes completed daily **OHLC candle analysis** (body/wicks, doji, pin bars, engulfing and inside-bar detection), 20/50-day trend, RSI-14, MACD/signal/histogram, ATR-14, Bollinger bands, and 20-bar support/resistance. Yahoo daily bars newer than 48 hours are conservatively excluded; the latest accepted bar may be older than a trading session and bars older than four calendar days are flagged for review (weekends/holidays can explain the warning). OHLC is adjusted consistently. Portfolio FX legs use signed base units and supplied average price, not current valuation, and are listed separately without netting. The brief does not use a live economic-calendar, bid/ask, liquidity, financing, tax, leverage, or personal-suitability feed; all omissions are returned as warnings. Add `--with-news` only when a fresh, paid multi-agent news research run is wanted.

`fx-scan` ranks the default major pairs (EUR/USD, GBP/USD, USD/JPY, USD/CHF, USD/CAD, AUD/USD and NZD/USD) by the deterministic trend-strength score, with data timestamps, reference risk levels, and data availability warnings. `fx-scan --with-news` then runs fresh multi-agent market and news research for the highest-ranked directional candidate only; it requires `ANTHROPIC_API_KEY`, costs an API run, and reports the sources available to the underlying research pipeline. Neither mode claims exhaustive news coverage or treats a rank as an instruction to trade.

`strategy-backtest` simulates the same long/short/flat 20/50 trend rule. A signal uses a completed close and is filled at the following bar open; turnover costs are charged at each position change. Ending positions are marked at the last close without a hypothetical exit cost. The buy-and-hold comparison is measured from the first requested open to the last requested close, before costs. It reports strategy and buy-and-hold returns, drawdown, annualised statistics, and turnover events. It is independent of the LLM training cutoff because it makes no model calls. These outputs are historical research simulations, not investment recommendations or evidence of future performance.

## Free data sources (evaluated, not yet integrated)

The FX commands currently use Yahoo daily bars only. These free sources were checked in November 2026 as candidates for later integration; free tiers change, so re-check before relying on them.

| Source | Free tier | Would improve | Notes |
|---|---|---|---|
| ForexFactory weekly calendar JSON (`nfs.faireconomy.media/ff_calendar_thisweek.json`) | No key | Real upcoming high-impact events per currency, replacing the static event checklist | Unofficial feed, no uptime guarantee; cache and poll sparingly |
| OANDA v20 practice (demo) account | Free account and token | Bid/ask, intraday candles and an explicit `complete` flag per candle, replacing the 48-hour delay | Not offered by every OANDA entity; use read-only pricing and candle endpoints only |
| Twelve Data Basic | 800 credits/day, 8/minute | Intraday FX candles for the major pairs | Free key |
| Frankfurter (`api.frankfurter.dev`) | No key | Daily central-bank reference rate to cross-check Yahoo | No candles or spreads; not trading data |
| Alpha Vantage | 25 requests/day | — | Too small for regular scans |
| Finnhub | Free key, ~60 calls/minute | Economic calendar and FX candles are advertised | Whether these are on the free plan was not confirmed |

Any keyed source should read its key from your local `.env`, keep Yahoo as the fallback, and never place orders.

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

Every run makes many LLM calls across about 10 agents. Expect:
- an ensemble of N to cost about N times a single report;
- a backtest to cost about (tickers × dates) times a single report.

Start with one ticker and `--every 14`. Check your Anthropic console after the first run before scaling up.

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
- **Claude Code on your computer:** full mode. It runs the CLI and reads your open stock pages for live mode.
- **claude.ai (no API key):** fast chat mode. Claude runs the TradingAgents roles itself: prices and indicators come from Yahoo through Claude in Chrome in one batched call, and news comes from web search. There are no screenshots, about 4 tool calls in all, and the result is labelled as single-model.

To install in Claude Code, copy the folder to `~/.claude/skills/trading-agents/`. On claude.ai, upload the zipped folder under Settings → Capabilities → Skills.

## Upstream

This project is pinned to TradingAgents commit `9fa1196` (Apache-2.0). Bump the pin in `pyproject.toml` deliberately, then re-run `pytest`.
