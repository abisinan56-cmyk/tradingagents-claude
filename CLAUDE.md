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
   - creates `.env`.
   The first run takes a few minutes. If it says Python 3.11+ is missing, tell the user the `brew` or `uv` command it printed, and stop.
3. **API key:** if `ANTHROPIC_API_KEY` is missing (`ta-claude report` exits with code 2 and says so), ask the user to paste the key into `.env` themselves. Give them `open -e .env`. Never read, print, edit or ask for the key in chat.

## Doing the work
Follow the `trading-agents` skill: `skill/trading-agents/SKILL.md`, also installed user-wide by `setup.sh`. Read it before the first analysis in a session.

Quick map:

| Request | Command |
|---|---|
| A rating for one ticker or pair | `ta-claude report <T> --json` |
| How sure is it | `ta-claude ensemble <T> -n 5 --json` |
| Track record | `ta-claude backtest <T1,T2> --start <after 2026-06-30> --end ... --every 7 --json` |
| Against holdings | add `--portfolio <file.json>` |
| Live, on a page or app the user has open | skill section 2: read the screen into `quote.json`, then `ta-claude live <T> --quote quote.json --json` |
| What market is this | `ta-claude market <T>` (free, instant) |
| Deterministic research plan | `ta-claude plan <T> --rating Buy --json` (no API key) |
| Technical strategy simulation | `ta-claude strategy-backtest <T> --start ... --end ... --json` (no API key) |
| Compare strategy suite | `ta-claude strategy-suite EURUSD --start ... --end ... --json` (no API key) |
| Rank current major-FX setups | `ta-claude fx-scan --json` (no API key) |
| Add fresh news research to top FX candidate | `ta-claude fx-scan --with-news --json` (API cost) |
| Structured FX research brief | `ta-claude fx-brief EURUSD --json` (no API key) |
| Add fresh news research to an FX brief | `ta-claude fx-brief EURUSD --with-news --json` (API cost) |

Tickers:
- US: `NVDA`
- Dubai DFM: `EMAAR.AE`
- India: `RELIANCE.NS`
- Crypto: `BTC-USD`
- FX: `EURUSD`

Abu Dhabi (ADX) stocks are not on Yahoo, so only live mode works for them.

Rules:
- Full runs take minutes and cost API usage. Run them in the background and don't start a second run while one is going.
- Confirm cost first for any backtest over 10 cells, any ensemble with n over 5, and any `live --full`.
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
  - `markets.py`: ticker classification
  - `cutoff.py`: look-ahead guard
  - `config.py`: Claude models and benchmarks
- Upstream TradingAgents is pinned in `pyproject.toml`. Bump the pin deliberately and re-run the tests.
- Data lives in `~/.ta-claude`: results, replay files and the memory log.
