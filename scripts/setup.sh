#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
UV="/opt/homebrew/bin/uv"
PYTHON="/opt/homebrew/bin/python3.14"
[ -x "$UV" ] || { echo "uv não encontrado" >&2; exit 1; }
[ -d .venv ] || "$UV" venv --python "$PYTHON" .venv
"$UV" pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
