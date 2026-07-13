# Agente Autônomo de Candidaturas — Implementation Plan

> **For Hermes:** executar com TDD e validar cada integração antes de habilitar autoenvio.

**Goal:** coletar vagas horariamente, priorizar até 10 candidaturas aderentes por dia, preencher ATS externos, aprender com feedback e entregar relatório diário auditável.

**Architecture:** pipeline local orientado a estado em SQLite. O scraper existente produz candidatos; o agente ingere, pontua, resolve o ATS, preenche via Playwright com adaptadores e registra toda decisão. `computer_use` fica restrito a diálogos nativos/fallback; não é o motor principal.

**Tech Stack:** Python 3.14, SQLite, Playwright, `http.server`, Hermes cron.

---

## Política operacional

1. `AUTO_SUBMIT=false` durante calibração e testes.
2. Só autoenviar quando: score mínimo atingido, domínio ATS permitido, nenhum campo bloqueante, CV disponível e ausência de CAPTCHA/login/2FA.
3. Nunca responder por inferência a salário, autodeclaração, deficiência, antecedentes, conflito de interesse, autorização legal ou patrocínio de visto.
4. Perguntas factuais já aprovadas entram no banco de respostas e deixam de exigir validação.
5. Toda candidatura usa chave idempotente `job_url + company + title`; nunca envia duas vezes.
6. Meta diária é teto operacional, não motivo para reduzir qualidade.

## Fases

### Fase 1 — Núcleo auditável
- Criar schema SQLite para vagas, candidaturas, eventos, respostas e feedback.
- Ingerir `~/Projetos/vagas_linkedin_new.json` sem duplicação.
- Aplicar score determinístico explicável e fila diária.
- Produzir relatório diário em Markdown.

### Fase 2 — Automação web
- Playwright com perfil persistente dedicado.
- Detectar ATS por domínio/DOM.
- Adaptadores iniciais: Greenhouse, Lever, Ashby e genérico.
- Workday/Gupy em modo assistido até validação real.
- Bloquear CAPTCHA, login, 2FA e perguntas desconhecidas.

### Fase 3 — Painel e feedback
- Dashboard local em `127.0.0.1:8765` com auto-refresh.
- Botões `boa`, `ruim`, `irrelevante` e motivo opcional.
- Atualizar pesos apenas dentro de limites, preservando regras duras de localização/senioridade.

### Fase 4 — Cron e operação
- Coleta/preenchimento de hora em hora durante janela configurada.
- Relatório diário após o último ciclo.
- Controle de execução em `data/run_control.json` e estado em SQLite.
- Alertar somente bloqueios novos; silêncio quando não houver trabalho.

## Testes obrigatórios

- Ingestão idempotente.
- Política de autoenvio e campos bloqueantes.
- Limite diário de 10.
- Feedback altera score sem violar filtros duros.
- Relatório reflete apenas dados persistidos.
- Adaptadores testados primeiro contra fixtures HTML locais.
- Simulação ponta a ponta com `AUTO_SUBMIT=false`.

## Critério para habilitar autoenvio

- Testes verdes.
- Um login manual por plataforma, quando necessário.
- Banco de respostas completo para campos bloqueantes.
- Pelo menos 5 candidaturas em modo simulação revisadas sem erro material.
- Autorização única do usuário para mudar `AUTO_SUBMIT` para `true` nos domínios aprovados.
