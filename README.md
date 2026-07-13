# Candidatura Agent

Agente local para buscar, priorizar, preencher e acompanhar candidaturas de emprego com o mínimo de intervenção humana.

## Decisão técnica

**Playwright é o motor principal.** Ele acessa o DOM, mantém sessão e permite testar seletores. `computer_use` é fallback para componentes nativos e verificação visual; usá-lo como motor de formulário seria uma roleta com botões.

## Fluxo

1. O scraper existente atualiza `~/Projetos/vagas_linkedin_new.json`.
2. `hourly.py` ingere vagas, calcula aderência e seleciona a fila do dia.
3. O navegador resolve o destino externo e usa um adaptador de ATS.
4. Campos conhecidos são preenchidos; campos bloqueantes pausam apenas aquela vaga.
5. O resultado e todas as decisões ficam no SQLite.
6. O dashboard recebe feedback e ajusta pesos.
7. `daily_report.py` gera o resumo diário.

## Modos

- `dry_run`: preenche, registra e não envia.
- `auto_submit`: envia apenas em domínios aprovados e sem bloqueios.
- `manual_only`: registra a vaga para ação humana.

## Segurança e autonomia

O sistema não digita senhas, não resolve CAPTCHA/2FA e não inventa respostas legais, salariais ou demográficas. Depois que uma resposta for aprovada uma vez, ela pode ser reutilizada automaticamente.

## Comandos

```bash
./scripts/setup.sh
./scripts/run_hourly.sh
./scripts/run_report.sh
./scripts/run_dashboard.sh
.venv/bin/python -m pytest -q
```

Dashboard: `http://127.0.0.1:8765`

## Estrutura

```text
src/candidatura_agent/  núcleo, banco, política, browser e dashboard
data/                   SQLite, perfil local e controle de execução
reports/                relatórios diários
scripts/                wrappers para cron
```

## Estado atual

A implementação começa em modo `dry_run`. O autoenvio só será liberado depois da calibração única, teste com ATS real e autorização explícita.
