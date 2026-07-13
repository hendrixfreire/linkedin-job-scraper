#!/bin/bash
set -euo pipefail
PROJECT="/Users/hendrixfreire/Projetos/candidatura-agent"
cd "$PROJECT"

printf 'CANDIDATURA AGENT\n'
printf 'Projeto: %s\n\n' "$PROJECT"

printf 'Dashboard: '
if /usr/bin/curl -fsS --max-time 2 http://127.0.0.1:8765/api/health >/dev/null; then
  printf 'ATIVO — http://127.0.0.1:8765\n'
else
  printf 'INATIVO\n'
fi

.venv/bin/python - <<'PY'
import json, sqlite3
from pathlib import Path
root = Path('/Users/hendrixfreire/Projetos/candidatura-agent')
config = json.loads((root / 'config.json').read_text())
control_path = root / 'data/run_control.json'
control = json.loads(control_path.read_text()) if control_path.exists() else {}
conn = sqlite3.connect(root / 'data/candidaturas.db')
conn.row_factory = sqlite3.Row
by_status = {r['status']: r['n'] for r in conn.execute('SELECT status, COUNT(*) n FROM jobs GROUP BY status')}
print(f"Modo: browser_enabled={config['browser_enabled']} | auto_submit={config['auto_submit']}")
print(f"ATS permitidos: {', '.join(config['allowed_ats'])}")
print(f"Score mínimo: {config['min_fit_score']} | limite diário: {config['daily_limit']}")
print(f"Última execução: {control.get('finished_at', 'sem registro')} | status={control.get('status', 'n/a')}")
print(f"Vagas: {sum(by_status.values())} | " + ' | '.join(f"{k}={v}" for k, v in sorted(by_status.items())))
print(f"Candidaturas registradas: {conn.execute('SELECT COUNT(*) FROM applications').fetchone()[0]}")
print(f"Feedbacks: {conn.execute('SELECT COUNT(*) FROM feedback').fetchone()[0]}")
last = conn.execute('''SELECT a.status,a.ats,j.title,j.company,a.updated_at FROM applications a JOIN jobs j ON j.id=a.job_id ORDER BY a.updated_at DESC LIMIT 1''').fetchone()
if last:
    print(f"Última candidatura: {last['status']} | {last['company']} — {last['title']} | {last['ats']} | {last['updated_at']}")
PY

printf '\nGit: '
if [[ -z "$(git status --short)" ]]; then
  printf 'limpo\n'
else
  printf 'há alterações não commitadas\n'
  git status --short
fi

printf '\nMapa: %s/docs/COMO-FUNCIONA.md\n' "$PROJECT"
printf 'Diagrama: %s/docs/arquitetura.html\n' "$PROJECT"
