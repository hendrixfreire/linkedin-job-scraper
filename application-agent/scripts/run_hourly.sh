#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python -m candidatura_agent.hourly
exec .venv/bin/python -m candidatura_agent.notifications
