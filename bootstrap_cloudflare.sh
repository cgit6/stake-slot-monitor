#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

VENV="${STAKE_BOOTSTRAP_VENV:-$HOME/.stake-slot-monitor-venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ ! -x "$VENV/bin/python" ]]; then
  "$PYTHON_BIN" -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/pip" install -r requirements.txt
"$VENV/bin/python" -m playwright install chromium

exec "$VENV/bin/python" stake_top50.py --bootstrap
