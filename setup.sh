#!/usr/bin/env bash
# One-step setup for macOS/Linux: Python env, ta-claude, Claude Code skill, .env.
# Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

# The Python environment lives outside the repo: if the repo is in an iCloud-synced
# folder (Documents, Desktop), thousands of venv files would sync and could be evicted.
VENV="${TA_VENV:-$HOME/.ta-claude/venv}"
mkdir -p "$(dirname "$VENV")"

# 1. Python 3.11+ (macOS ships 3.9, which is too old)
PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  if command -v uv >/dev/null 2>&1; then
    say "No Python 3.11+ found; using uv to provide Python 3.13"
    uv venv --python 3.13 "$VENV"
  else
    say "Python 3.11 or newer is required."
    echo "Install it with ONE of:"
    echo "  brew install python@3.13                      (Homebrew)"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh  (uv, then re-run this script)"
    exit 1
  fi
else
  say "Using $($PY --version)"
  [ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
fi

# 2. Install ta-claude (pulls TradingAgents from GitHub)
say "Installing ta-claude and TradingAgents (a few minutes the first time)"
"$VENV/bin/python" -m pip install --upgrade pip -q
"$VENV/bin/python" -m pip install -e ".[test]" -q

# 3. Offline tests
say "Running offline tests"
"$VENV/bin/python" -m pytest -q

# 4. Claude Code skill
mkdir -p "$HOME/.claude/skills"
rm -rf "$HOME/.claude/skills/trading-agents"
cp -R skill/trading-agents "$HOME/.claude/skills/trading-agents"
say "Installed the Claude Code skill at ~/.claude/skills/trading-agents"

# 5. ta-claude on PATH (symlink into ~/.local/bin)
mkdir -p "$HOME/.local/bin"
ln -sf "$VENV/bin/ta-claude" "$HOME/.local/bin/ta-claude"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) if ! grep -qs '.local/bin' "$HOME/.zshrc"; then
       echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.zshrc"
     fi
     say "ta-claude is in ~/.local/bin; open a new Terminal window to use it";;
esac

# 6. .env
if [ ! -f .env ]; then
  cp .env.example .env
  say "Created .env. Open it and paste your ANTHROPIC_API_KEY:"
  echo "  open -e $PWD/.env"
else
  say ".env already exists; left unchanged"
fi

# 7. Data check
say "Checking Yahoo Finance access"
"$VENV/bin/python" -c "import yfinance as y; n = len(y.Ticker('SPY').history(period='5d')); print('Yahoo OK' if n else 'Yahoo returned no data')" 2>/dev/null || echo "Yahoo check failed: check your internet connection"

say "Done. Try:  ta-claude market EMAAR.AE,EURUSD   then, after adding your key:  ta-claude report NVDA"
