# ta-claude

[TradingAgents](https://github.com/TauricResearch/TradingAgents) running on Claude. It adds fixes for the framework's main limitations, and presets for US, UAE, India, crypto and FX.

> Research tool only. Not financial, investment or trading advice.

## What it fixes

| Upstream limitation | Fix here |
|---|---|
| Two runs of the same ticker and date can differ | `ensemble` runs N times, takes a majority vote and reports the agreement rate (high ≥80%, medium ≥60%, low below that). `temperature=0` is the default. |
| Live news and social feeds drift, so a run can't be reproduced | `report` records every LLM answer **and** every data-tool output to SQLite. Re-running the same ticker and date replays them exactly, at no API cost. |
| The model may already know the outcome of past dates (look-ahead) | `backtest` refuses dates on or before the models' training cutoff. Override with `--allow-contaminated`, and the results are flagged. |
| Social feeds leak the future into backtests | Backtests drop the social analyst automatically. |
| No baselines, no costs, no significance test | Backtests report results net of round-trip costs, a bootstrap 95% CI, hit rate, and three baselines: always-long, the benchmark, and random direction. |
| An ensemble would flood the memory log | Ensemble members write to copies of the log. Only the consensus is recorded. |
| Cost | Opus 5.5 runs only the two manager agents; Sonnet 5 runs the rest. Debate and risk rounds default to 1. Replays are free. |

## Markets

| Market | Example | Pipeline | Alpha benchmark | Point-in-time fundamentals |
|---|---|---|---|---|
| US | `NVDA` | stock, all 4 analysts | SPY | Yes (SEC EDGAR) |
| UAE | `EMAAR.AE` | stock, no social | `UAE` ETF (proxy) | No |
| India | `RELIANCE.NS` | stock, no social | Nifty / Sensex | No |
| Crypto | `BTC-USD` | asset | SPY | n/a |
| FX | `EURUSD`, `GBPJPY=X`, `USDAED` | asset, market + news | US Dollar Index | n/a |

FX pairs get Yahoo's `=X` suffix automatically. Pegged pairs such as USDAED or USDSAR are flagged, because they barely move. Judge FX calls on raw return rather than on alpha.

Before running, check a ticker's classification with `ta-claude market EMAAR.AE,EURUSD`. Also confirm any UAE ticker on finance.yahoo.com first, because Yahoo's DFM and ADX coverage is uneven.

## Install

```bash
git clone <this repo> && cd <repo>
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[test]"
cp .env.example .env    # add ANTHROPIC_API_KEY
pytest -q               # offline tests, no key needed
```

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
```

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

## Claude skill

`skill/tradingagents-claude/SKILL.md` lets Claude (Claude Code, or Claude with a shell) run this project for you from plain requests. See that file to install it.

## Upstream

This project is pinned to TradingAgents commit `9fa1196` (Apache-2.0). Bump the pin in `pyproject.toml` deliberately, then re-run `pytest`.
