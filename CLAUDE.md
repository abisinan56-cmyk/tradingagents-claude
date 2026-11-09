# ta-claude: TradingAgents on Claude

Multi-agent stock, crypto and FX analysis (TradingAgents, pinned upstream commit) running on Claude. It adds:
- record/replay of runs;
- ensembles;
- look-ahead-safe backtests;
- a live mode that reads the price off the user's screen.

Research only, never advice.

## First run: set up if needed
1. Find the CLI. Try `ta-claude`, then `~/.local/bin/ta-claude`, then `~/.ta-claude/venv/bin/ta-claude`. Use the first that works for the whole session.
2. If none works, run `./setup.sh`. It:
   - creates the venv in `~/.ta-claude/venv`, outside this folder, because this folder may be in iCloud;
   - installs the package and runs the tests;
   - installs the skill to `~/.claude/skills/trading-agents`;
   - creates `.env` for optional settings.
   The first run takes a few minutes. If it says Python 3.11+ is missing, tell the user the `brew` or `uv` command it printed, and stop.
3. **No API key is needed.** Never ask the user for an API key and never read `.env`. Without a key, `report` and `ensemble` return a keyless research pack, and you write the TradingAgents analysis from it (skill section 0, keyless mode), enriching it only with the connectors available in this Claude session: Firecrawl, Twelve Data, Claude in Chrome and web search.

## Doing the work
Follow the `trading-agents` skill: `skill/trading-agents/SKILL.md`, also installed user-wide by `setup.sh`. Read it before the first analysis in a session.

Quick map:

| Request | Command |
|---|---|
| A rating for one ticker or pair | `ta-claude research <T> --json`, then write the analysis (skill section 0) |
| How sure is it | write the analysis from the pack and state confidence from agreement between the 20/50 regime, the candle, RSI/MACD and the news |
| Track record | `ta-claude strategy-suite <T> --start ... --end ... --json` |
| Against holdings | add `--portfolio <file.json>` to `fx-brief` |
| Live, on a page or app the user has open | skill section 2: read the screen into `quote.json`, then `ta-claude live <T> --quote quote.json --json` |
| What market is this | `ta-claude market <T>` (free, instant) |
| Deterministic research plan | `ta-claude plan <T> --rating Buy --json` |
| Technical strategy simulation | `ta-claude strategy-backtest <T> --start ... --end ... --json` |
| Rank current major-FX setups | `ta-claude fx-scan --json` |
| News for the top FX candidate | `ta-claude fx-scan --with-news --json` |
| Structured FX research brief | `ta-claude fx-brief EURUSD --json` |
| News on an FX brief | `ta-claude fx-brief EURUSD --with-news --json` |

Every command above works with no API key.

Tickers:
- US: `NVDA`
- Dubai DFM: `EMAAR.AE`
- India: `RELIANCE.NS`
- Crypto: `BTC-USD`
- FX: `EURUSD`

Abu Dhabi (ADX) stocks are not on Yahoo, so only live mode works for them.

Rules:
- Keyless commands take seconds and cost nothing. Use connectors sparingly: a few Firecrawl scrapes and one Twelve Data quote per analysis.
- Live mode is **read-only**. Never click order or trade buttons, never enter credentials, never place trades.
- End every analysis with: research only, not financial advice.

## Developing
- Tests (offline, no key): `~/.ta-claude/venv/bin/python -m pytest -q`. Keep them passing, and add a test for every bug fixed.
- Layout:
  - `ta_claude/cli.py`: commands
  - `runner.py`: report, ensemble, backtest and scoring
  - `replay.py`: record and replay
  - `live.py`: screen vs Yahoo
  - `model.py`: deterministic trend, candle/indicator, risk, FX scan and brief analysis; `technical_snapshot` feeds the agents
  - `runner.py` also defines `TaClaudeGraph`, the upstream graph plus that snapshot in every agent prompt
  - `llm.py`: makes upstream's structured agents use Anthropic `json_schema` output (applied when `runner` loads); bump `runner.PROMPT_VERSION` whenever prompts or LLM request shape change
  - `research.py`: keyless research pack (Yahoo data, snapshot, plan, FX brief, dated headlines, connector and analysis steps)
  - `markets.py`: ticker classification
  - `cutoff.py`: look-ahead guard
  - `config.py`: Claude models and benchmarks
- Upstream TradingAgents is pinned in `pyproject.toml`. Bump the pin deliberately and re-run the tests.
- Data lives in `~/.ta-claude`: results, replay files and the memory log.
