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
| Cost | Opus 5.5 runs only the two manager agents; Sonnet 5 runs the rest. Debate and risk rounds default to 1. Replays are free. |

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

## Install

macOS or Linux, one step:

```bash
git clone https://github.com/abisinan56-cmyk/tradingagents-claude && cd tradingagents-claude
./setup.sh
```

The script:
1. finds Python 3.11 or newer and creates `.venv`;
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
```

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
- **claude.ai:** browser-only mode. Live reads work through Claude in Chrome. For a full multi-agent run, Claude gives you the command to run on your machine, because the claude.ai sandbox can't reach Yahoo.

To install in Claude Code, copy the folder to `~/.claude/skills/trading-agents/`. On claude.ai, upload the zipped folder under Settings → Capabilities → Skills.

## Upstream

This project is pinned to TradingAgents commit `9fa1196` (Apache-2.0). Bump the pin in `pyproject.toml` deliberately, then re-run `pytest`.
