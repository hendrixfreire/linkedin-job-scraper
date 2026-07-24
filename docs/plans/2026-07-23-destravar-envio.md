# Plano de destravamento do envio automático

**Data:** 23/07/2026
**Contexto:** o agente registra ~20 mil avaliações, mas enviou 5 candidaturas no total.
O relatório diário reporta vagas bloqueadas todo dia (aderência 80/100, ATS Greenhouse).

## Diagnóstico do funil

| Etapa | Volume | Onde trava |
|---|---|---|
| Vagas avaliadas | 313 | — |
| Rejeitadas por aderência (< 75) | 256 | `policy.assess_job` |
| Qualificadas | 57 | — |
| Com `apply_url` resolvida | 2 | `assets.validate_external_apply_url` |
| Chegaram ao formulário | 17 | — |
| Bloqueadas no formulário | 19 | `adapters.classify_field` |
| Enviadas | 5 | `config.auto_submit` |

## Achado central

O `profile.json` já contém as respostas (CPF, raça, gênero, deficiência, salário,
autorização de trabalho, nível de idioma) e ainda um bloco `greenhouse_recurring_answers`
com 13 respostas prontas. **Nenhum desses dados é lido por qualquer módulo.**
A tabela `answers` do schema tem zero linhas e nenhum código que a leia ou escreva.

O agente bloqueia por falta de resposta que ele já possui.

---

## P1 — `adapters.py`: parar de bloquear pergunta que já tem resposta

### Problema
`classify_field` é uma allowlist de ~16 rótulos. O fallback é
`FieldRule(None, True, "pergunta desconhecida")`. Um formulário Greenhouse brasileiro
tem 10–25 perguntas customizadas; todas caem no fallback. Se obrigatórias, viram blocker.

Além disso `BLOCKED_TERMS` bloqueia por categoria (`salary`, `race`, `gender`,
`disability`, `work authorization`) mesmo com resposta explícita no perfil.

### Correção
1. `classify_field(label, answers=None)` passa a aceitar um dicionário de respostas
   disponíveis. Sem o argumento, mantém o comportamento conservador atual.
2. Nova função `build_answer_book(profile)` que consolida, em ordem de precedência:
   - `profile["question_answers"]` (novo bloco, match por texto normalizado da pergunta);
   - `profile["greenhouse_recurring_answers"]` (já existe, hoje ignorado);
   - chaves diretas do perfil.
3. Ordem de decisão em `classify_field`:
   - identidade conhecida (nome, e-mail, telefone, CV, LinkedIn) → preenche;
   - pergunta com resposta aprovada explícita → preenche, **inclusive se sensível**;
   - pergunta sensível sem resposta → bloqueia;
   - pergunta desconhecida → bloqueia.

### Garantia preservada
Toda resposta vem de `profile.json`, sob controle do usuário. Nenhuma resposta é
inferida, gerada ou deduzida do texto da vaga.

### Teste (TDD)
- "Qual sua identidade de gênero?" com resposta no perfil → não bloqueia.
- "Qual sua identidade de gênero?" sem resposta no perfil → bloqueia.
- Pergunta desconhecida sem resposta → continua bloqueando.

---

## P2 — `browser.py`: selects e escolhas que falham por texto exato

### Problema
`field.select_option(label=str(value))` exige match textual idêntico. O perfil diz
`"Brazil"`, o select oferece `"Brazil (Brasil)"` → blocker
`"Country: opção aprovada não encontrada"`.

Radios e checkboxes de pergunta ("Sim" / "Não" / "De acordo") não são casados por
rótulo da opção — só por valor booleano do perfil.

### Correção
1. `select_matching_option(field, value)`: tenta match exato → normalizado
   (minúsculas, sem acento, sem pontuação) → prefixo/substring **desde que único**.
   Ambíguo ou ausente → blocker explícito com as opções disponíveis.
2. Grupos de radio/checkbox: casar a resposta contra o rótulo de cada opção do grupo,
   com a mesma escada de tolerância.

### Teste (TDD)
- Select com `Brazil (Brasil)` e perfil `Brazil` → seleciona.
- Select com duas opções contendo o valor → blocker por ambiguidade.
- Grupo de radio `Sim`/`Não` com resposta `Sim` → marca a correta.

---

## P3 — `assets.py`: registro de ATS estreito demais

### Problema
`validate_external_apply_url` só aceita 6 hosts. Quinze vagas falharam com
`"URL oficial confirmada, mas ATS proprietário não reconhecido pelo validador"` —
a URL estava certa, o validador é que não reconhece o ATS.

`adapters.detect_ats` e `assets.ATS_HOST_MARKERS` são duas listas divergentes
mantidas à mão.

### Correção
1. Registro único de ATS em `adapters.py`, consumido por ambos os módulos.
2. Ampliar para os ATS realmente usados no Brasil e em vagas remotas:
   gupy, solides, abler, kenoby/pandapé, inhire, quickin, compleo, recruitee,
   workable, teamtailor, smartrecruiters, workday, icims, bamboohr, jobvite,
   taleo/oraclecloud, successfactors, breezy, jazzhr, vagas.com, infojobs.
3. A proibição de apontar para o LinkedIn permanece intacta.

### Teste (TDD)
- URL Workday/SmartRecruiters/Gupy → ATS reconhecido.
- URL do LinkedIn → continua rejeitada.
- HTTP simples → continua rejeitada.

---

## P4 — Vagas presas em `blocked`

### Problema
`hourly.run_pipeline` pula vagas com status `blocked` e `daily_queue` exige
`applications.id IS NULL`. As 17–19 vagas bloqueadas **nunca serão retentadas**,
mesmo depois das correções acima.

### Correção
`Database.reopen_blocked_jobs()` que devolve à fila as vagas bloqueadas por motivos
agora resolvíveis, apagando a application correspondente e registrando evento
auditável `application_reopened`. Bloqueios humanos (captcha, 2FA, login) permanecem.

### Teste (TDD)
- Vaga bloqueada por campo obrigatório → volta para `qualified`.
- Vaga bloqueada por captcha → permanece `blocked`.

---

## P5 — `config.json`: ligar o autoenvio de forma calibrada

### Problema
`"auto_submit": false` faz `run_application` retornar `dry_run` mesmo com formulário
limpo. `allowed_ats` tem apenas `greenhouse`.

### Correção
Executar um ciclo em dry-run com P1–P4 aplicados, conferir os screenshots
`reports/screenshots/job-*/last-application-pre-submit.png`, e só então ligar
`auto_submit`. Decisão final é do usuário — o código não vira a chave sozinho.

---

## Ordem de execução

1. P1 (adapters) — maior impacto direto nas notificações diárias
2. P2 (selects) — desbloqueia o resto do formulário
3. P3 (registro de ATS) — recupera 15 vagas com URL válida
4. P4 (reabrir bloqueadas) — devolve o estoque à fila
5. Suíte completa verde
6. P5 (dry-run + decisão do usuário sobre `auto_submit`)

---

## P6 — Página sem formulário passava como pronta (descoberto na execução)

### Problema
`run_application` concluía `dry_run` quando não havia bloqueios. Uma vaga removida
devolve uma página de erro sem nenhum campo — zero campos obrigatórios, zero
bloqueios, "pronta para envio". Das 9 vagas que apareceram prontas no primeiro
ciclo, 4 eram páginas mortas (`?error=true`) e 2 eram Ashby, cujo formulário só é
montado depois de um clique em "Apply".

### Correção
Ausência de preenchimento **e** ausência de bloqueio passa a ser o bloqueio
`formulário de candidatura não encontrado`. "Nada aconteceu" nunca mais é lido
como "tudo certo".

### Pendência conhecida
Formulários que só abrem após clique (Ashby) continuam bloqueados. Resolver exige
um passo de abertura antes do preenchimento — fora do escopo deste plano.

---

## Resultado da execução (23/07/2026)

| Momento | Prontas para envio | Bloqueadas |
|---|---|---|
| Antes | 0 | 19 |
| Depois de P1–P4 | 6 (4 falsas) | 12 |
| Depois de P1–P6 | 3 reais | 15 |

Prontas e verificadas: C6 Bank (Supervisor de Operações Sênior), C6 Bank
(Analytics Engineer | Dados), Ruby Labs (Lead Billing Data Analyst).

Bloqueios remanescentes: 10 por perguntas sem resposta aprovada (anos de
experiência por tecnologia, histórico de emprego estruturado, benefícios atuais,
salário anual em USD, escritório de preferência) e 5 por ausência de formulário.

`auto_submit` permanece `false` — o envio único autorizado ainda não ocorreu
porque a vaga escolhida (Getnet) havia sido removida do ATS.

## Invariantes que não mudam

- Nenhuma resposta factual inventada.
- Nenhum envio fora de ATS aprovado.
- Nenhum envio sem confirmação verificável na página.
- Captcha, 2FA e login continuam bloqueando.
- Toda transição de status gera evento auditável.
