#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

UV="${UV:-uv}"
command -v "$UV" >/dev/null || { echo "uv was not found; install it first: https://docs.astral.sh/uv/" >&2; exit 1; }

[ -d .venv ] || "$UV" venv .venv
"$UV" pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
