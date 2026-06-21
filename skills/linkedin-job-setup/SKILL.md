---
name: linkedin-job-setup
description: Entrevista o usuário pra configurar o scraper de vagas do LinkedIn. Pergunta uma coisa de cada vez com resposta recomendada, depois atualiza o linkedin_jobs.py com as configurações personalizadas, valida com uma execução de teste, e ativa o cron job. Use quando o usuário quer personalizar o scraper de LinkedIn pela primeira vez ou mudar parâmetros de busca existentes.
---

# LinkedIn Job Setup

Entreviste o usuário para coletar todos os parâmetros necessários para configurar o scraper de vagas do LinkedIn (`linkedin_jobs.py`). Faça perguntas **uma de cada vez**, sempre oferecendo uma **resposta recomendada** baseada em padrões comuns do mercado.

## Fluxo de execução

### Passo 1 — Confirmar setup técnico

Antes da entrevista, confirme:

1. O Hermes Agent está instalado? (`hermes --version`)
2. O Telegram está conectado? (pergunte: "você já conectou seu Telegram ao Hermes?")
3. O scraper está clonado? (`ls ~/linkedin-job-scraper/linkedin_jobs.py` ou o path que o usuário usou)

Se algum item faltar, **NÃO prossiga** — aponte pro README e explique o passo que falta.

### Passo 2 — Entrevista (uma pergunta por vez)

Faça as perguntas abaixo **uma de cada vez**. Pra cada uma, mostre sua **resposta recomendada** em itálico. Se o usuário aceitar a recomendação, avance. Se ele disser algo próprio, use o que ele disse.

Use o tool `clarify` com `choices` sempre que fizer sentido (escolha entre opções claras). Pra respostas abertas (nome, cargo), use `clarify` sem `choices`.

#### Bloco A — Identidade

**A1. Nome do usuário**
- Pergunta: "Qual nome devo usar no cabeçalho do arquivo de vagas?"
- Recomendado: o primeiro nome que aparece no profile do Hermes (se disponível) ou "User"
- Vai pra: `LINKEDIN_USER_NAME`

#### Bloco B — Cargo-alvo e senioridade

**B1. Área principal**
- Pergunta: "Qual é sua área principal?"
- Choices: `["Data Engineer", "Data Analyst", "Analytics Engineer", "BI/Analytics Manager", "AI/Machine Learning", "Outra (digite)"]`
- Vai pra: base das keywords

**B2. Senioridade alvo**
- Pergunta: "Qual nível de senioridade você busca?"
- Choices: `["Sênior", "Sênior/Lead", "Manager/Head", "Director+", "Pleno (apenas match perfeito)", "Indiferente"]`
- Recomendado: "Sênior" (mercado BR)
- Vai pra: filtro `f_E` e comportamento do `heuristic_score`

**B3. Excluir cargos júnior/pleno?**
- Pergunta: "Quer excluir vagas explicitamente marcadas como júnior, pleno, estágio ou trainee?"
- Choices: `["Sim, excluir todos", "Excluir júnior/estágio, manter pleno", "Não excluir nada"]`
- Recomendado: "Sim, excluir todos"
- Vai pra: lista `junior_kw` em `heuristic_score` e filtro em `main()`

#### Bloco C — Stack técnico (pro score heurístico)

**C1. Stack de alta relevância**
- Pergunta: "Quais tecnologias/cargos são match perfeito pra você? Liste as principais (separadas por vírgula)."
- Recomendado: baseado na área de B1 — ex: Data Engineer → "data engineer, analytics engineer, bigquery, airflow, spark, dbt, python"
- Vai pra: `high_skills` em `heuristic_score()`

**C2. Stack de média relevância**
- Pergunta: "E quais tecnologias/cargos são match parcial? (stack adjacente que você consegue fazer, mas não é seu core)"
- Recomendado: baseado em B1 — ex: "data analyst, data scientist, business intelligence, sql, etl"
- Vai pra: `mid_skills` em `heuristic_score()`

#### Bloco D — Localização e modalidade

**D1. Modalidades aceitas**
- Pergunta: "Quais modalidades de trabalho você aceita?"
- Choices: `["Remoto apenas", "Remoto + Híbrido", "Remoto + Híbrido + Presencial", "Tudo (qualquer modalidade)"]`
- Recomendado: "Remoto + Híbrido"
- Vai pra: filtro de `work_mode` em `fetch_one()`

**D2. Localização principal**
- Pergunta: "Qual região buscar?"
- Choices: `["Brasil (remoto) + São Paulo (híbrido/presencial)", "Apenas Brasil remoto", "Apenas São Paulo", "Outra cidade/região (digite)"]`
- Recomendado: "Brasil (remoto) + São Paulo (híbrido/presencial)"
- Vai pra: `build_searches()` (location e f_WT)

**D3. Cidade específica (se houve presencial/híbrido em D1/D2)**
- Pergunta: "Se houver vaga presencial, qual cidade deve ser aceita?"
- Recomendado: baseado em D2 — ex: "São Paulo"
- Vai pra: filtro `is_sp` em `fetch_one()` (regex `,\s*sp\b`)

#### Bloco E — Keywords de busca

**E1. Keywords customizadas**
- Pergunta: "Vou montar uma lista de keywords de busca baseada nas suas respostas. Quer adicionar ou remover alguma?"
- Recomendado: mostre a lista gerada a partir das respostas de B1+C1 e pergunte se quer editar
- Vai pra: lista `KEYWORDS` no topo do script

#### Bloco F — Frequência do cron

**F1. Frequência de execução**
- Pergunta: "Quantas vezes por dia o scraper deve rodar?"
- Choices: `["3x ao dia (8h, 13h, 18h)", "2x ao dia (manhã, tarde)", "1x ao dia (manhã)", "A cada hora", "Customizar horários"]`
- Recomendado: "3x ao dia (8h, 13h, 18h)"
- Vai pra: schedule do cron job (`0 8,13,18 * * *`)

### Passo 3 — Aplicar configurações

Depois de coletar todas as respostas:

1. **Leia o `linkedin_jobs.py`** do path que o usuário clonou
2. **Atualize**:
   - `USER_NAME` (default da env var `LINKEDIN_USER_NAME`)
   - `KEYWORDS` lista no topo
   - `build_searches()` — location e filtros `f_WT`, `f_E`
   - `high_skills` e `mid_skills` em `heuristic_score()`
   - `junior_kw` em `heuristic_score()` (se B3 = "não excluir", esvazie a lista)
   - Filtro `is_brazil` em `main()` (se D2 = outra região, ajuste)
   - Filtro `is_sp` em `fetch_one()` (se D3 = outra cidade)
3. **Crie o cron job** com o `cronjob` tool:
   - `schedule`: o que veio de F1
   - `prompt`: prompt do agente classificador (veja template abaixo)
   - `deliver`: `"origin"` (entrega no Telegram)
   - `skills`: `["cv-job-fit"]` se existir, senão `[]`
   - `enabled_toolsets`: `["terminal", "file"]`

### Passo 4 — Validação

1. **Rode o script uma vez**: `python3 <path>/linkedin_jobs.py`
2. **Verifique os outputs**: `jobs_new.json` deve ter vagas, `seen.json` deve ter IDs, `jobs.md` deve ter blocos
3. **Rode o dashboard**: `python3 <path>/linkedin_metrics.py`
4. **Mostre o resumo** pro usuário: quantas vagas novas, qual o yield por keyword
5. **Confirme o cron**: `cronjob action=list` e mostre o job criado

### Passo 5 — Wrap-up

1. Mostre um resumo final com:
   - Path do script configurado
   - Cron job ID e schedule
   - Path dos arquivos de saída
   - Como rodar o dashboard (`python3 <path>/linkedin_metrics.py`)
2. Pergunte: "Quer ajustar alguma keyword ou filtro agora, ou tá bom pra primeira execução?"

## Template do prompt do cron job

Use este template, preenchendo os valores da entrevista:

```
Você é um classificador de vagas de emprego do LinkedIn para o {USER_NAME}.

## Fluxo

1. Execute o script de coleta: `python3 {SCRIPT_PATH}`
2. Leia o JSON de vagas novas: `{OUTPUT_DIR}/jobs_new.json`
3. Se o JSON estiver vazio (`[]`), imprima apenas: "Nenhuma vaga nova." e termine.
4. Se houver vagas, leia o CV: `{CV_PATH}` (se disponível)
5. Cada vaga no JSON já vem com `heuristic_score` (1-5) e `heuristic_reason` pré-calculados.
6. **Use o heuristic_score como ponto de partida.** Apenas reavalie se o heuristic_reason parecer errono.
7. **Filtre APENAS vagas com 3+ estrelas.**
8. **Ordene da data de publicação mais recente para a mais antiga.** Vagas postadas hoje recebem emoji 🔥 no título.
9. Entregue no formato abaixo.

## Critérios de classificação (1-5 estrelas)

- ⭐⭐⭐⭐⭐ (5): Match perfeito — cargo, stack, nível e setor batem diretamente com a experiência.
- ⭐⭐⭐⭐ (4): Match forte — a maioria dos requisitos alinha, gaps pequenos.
- ⭐⭐⭐ (3): Match moderado — sobreposição parcial, precisaria se adaptar em 1-2 áreas.
- ⭐⭐ (2): Match fraco — gaps significativos.
- ⭐ (1): Match mínimo — sem sobreposição.

## Regra especial: vagas de nível Pleno

Vagas explicitamente marcadas como "Pleno" só podem aparecer com 5 estrelas.

## Formato de saída (Markdown para Telegram)

🔍 **N vagas novas** — data/hora

**1. ⭐⭐⭐⭐⭐ 🔥 Título da Vaga**
Empresa | Local | Modalidade
📅 Postada hoje | Match: frase curta justificando
[Ver vaga](url)

## Regras

- Responda em PT-BR
- Seja conciso — uma frase de justificativa por vaga
- Se nenhuma vaga atingir 3+ estrelas: "🔍 Nenhuma vaga com aderência suficiente desta vez."
- Sempre inclua data relativa de publicação
- 🔥 DEVE aparecer em vagas postadas hoje
```

## Batch mode

Quando o usuário sinalizar que quer acelerar — "faz tudo e manda pra validar", "não precisa ir passo a passo", "manda tudo de uma vez" — saia do modo pergunta-por-vez. Produza todas as configurações de uma vez baseado nas recomendações padrão, mostre o script configurado completo, e pergunte se quer validar ou ajustar algo.

## Quando NÃO usar esta skill

- O usuário só quer mudar UMA keyword isolada — edite direto
- O usuário quer debugar um problema — use debugging normal
- O usuário não tem o Hermes/Telegram configurado — aponte pro README primeiro

## Pitfalls

- **Não confie que o script está em `~/linkedin-job-scraper/`** — sempre pergunte o path onde clonou
- **Não crie o cron job antes de validar o script** — rode manualmente primeiro
- **Não esqueça de configurar `LINKEDIN_OUTPUT_DIR`** — se não setar, os arquivos vão pra `~/linkedin-jobs/` (ok, mas confirme com o usuário)
- **CV do usuário é opcional** — se não tiver, o agente classifica só pelo título/empresa/descrição
