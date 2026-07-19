#!/bin/bash
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT"

printf 'APPLICATION AGENT\n'
printf 'Project: %s\n\n' "$PROJECT"

if [ -f config.json ]; then
  PORT="$(python3 -c "import json; print(json.load(open('config.json')).get('dashboard_port', 8765))")"
  printf 'Dashboard: '
  if /usr/bin/curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/api/health" >/dev/null; then
    printf 'ACTIVE — http://127.0.0.1:%s\n' "$PORT"
  else
    printf 'INACTIVE\n'
  fi
else
  printf 'Dashboard: not configured (copy config.example.json to config.json)\n'
fi

printf '\nGit: '
if [[ -z "$(git status --short -- application-agent)" ]]; then
  printf 'clean\n'
else
  printf 'uncommitted changes\n'
  git status --short -- application-agent
fi
