# Candidatura Agent

## O que é
Pipeline local e auditável para candidaturas de emprego autônomas.

## Stack
- Python 3.14
- SQLite stdlib
- Playwright
- HTTP dashboard stdlib
- Hermes cron

## Estrutura
- `src/candidatura_agent/db.py`: schema e persistência
- `src/candidatura_agent/policy.py`: score, bloqueios e autoenvio
- `src/candidatura_agent/ingest.py`: importação do scraper
- `src/candidatura_agent/browser.py`: Playwright e adaptadores
- `src/candidatura_agent/dashboard.py`: painel e feedback
- `src/candidatura_agent/report.py`: relatório diário

## Convenções
- Código e nomes técnicos em inglês; UI e relatórios em PT-BR.
- Toda transição de status gera evento auditável.
- Nenhum envio fora de domínio permitido.
- Nenhuma resposta factual inventada.
- TDD obrigatório para comportamento novo.

## Build e teste
```bash
./scripts/setup.sh
.venv/bin/python -m pytest -q
```

## Estado atual
Implementação inicial em `dry_run`; autoenvio bloqueado até calibração.

## Referências
- `README.md`
- `docs/plans/2026-07-13-candidatura-autonoma.md`
- `AGENTS.md`
