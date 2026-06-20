# LinkedIn Job Scraper

Scraper em Python para a [API pública Guest do LinkedIn](https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search) que busca vagas de emprego, elimina duplicatas entre execuções, e prepara um arquivo JSON para um agente LLM classificar e reportar.

Feito pra rodar em cron sem nenhuma infraestrutura — sem banco de dados, sem autenticação, sem login no LinkedIn. Apenas arquivos em disco.

## Funcionalidades

- **Sem autenticação** — usa a API pública Guest do LinkedIn (scraping de HTML)
- **Deduplicação tripla**:
  1. IDs persistentes das vagas (`seen.json`)
  2. Chaves normalizadas título + empresa (pega vagas repostadas com ID novo)
  3. Lê os outputs anteriores do agente e pula vagas já reportadas
- **Scoring heurístico** — pré-calcula uma nota de 1-5 estrelas por vaga pra que o LLM só reavalie casos borderline (~80% de economia de tokens)
- **Tracking de yield por keyword** — remove automaticamente keywords que não produzem nada após 15+ execuções
- **Buscas paralelas com rate limiting** — 3 threads, 300ms entre páginas, deadline de 4 minutos
- **Filtro por localização e senioridade** — apenas Brasil/São Paulo, remove júnior/estágio
- **Dashboard de métricas** — vê yield por keyword, execuções recentes, tamanho da base

## Requisitos

- Python 3.8+
- Nenhuma dependência externa (apenas stdlib)

## Instalação

```bash
# Clonar
git clone https://github.com/hendrixfreire/linkedin-job-scraper.git
cd linkedin-job-scraper

# Tornar scripts executáveis (opcional)
chmod +x linkedin_jobs.py linkedin_metrics.py
```

Pronto. Sem `pip install`, sem virtualenv, sem chaves de API.

## Início Rápido

```bash
# Rodar uma vez — cria ~/linkedin-jobs/ com todos os arquivos de saída
python3 linkedin_jobs.py

# Ver o que foi coletado
cat ~/linkedin-jobs/jobs_new.json

# Conferir o histórico legível
head ~/linkedin-jobs/jobs.md

# Ver métricas
python3 linkedin_metrics.py
```

## Configuração

Todas as configurações específicas do usuário são feitas via variáveis de ambiente. Não há arquivo de config pra editar.

| Variável | Padrão | Descrição |
|----------|---------|-------------|
| `LINKEDIN_OUTPUT_DIR` | `~/linkedin-jobs` | Onde salvar os arquivos de saída (jobs.md, jobs_new.json, seen.json, keywords.json) |
| `LINKEDIN_USER_NAME` | `User` | Nome pra usar no cabeçalho do jobs.md |
| `LINKEDIN_CRON_OUTPUT_DIR` | _(desativado)_ | Diretório com os arquivos `.md` de resposta do agente. Quando definido, o scraper lê os últimos 3 arquivos e exclui vagas já reportadas ao usuário. Requer que o agente salve respostas como arquivos `.md` neste diretório. |

### Exemplo: diretório de saída personalizado

```bash
export LINKEDIN_OUTPUT_DIR=~/minha-busca-de-vagas
python3 linkedin_jobs.py
```

### Exemplo: ativar dedup entre execuções com um agente

Se você tem um agente LLM (ex: [Hermes Agent](https://hermes-agent.nousresearch.com), Claude, ChatGPT) classificando vagas e salvando respostas num diretório:

```bash
export LINKEDIN_CRON_OUTPUT_DIR=~/.meu-agente/outputs
python3 linkedin_jobs.py
```

O scraper vai ler os últimos 3 arquivos `.md` nesse diretório, extrair títulos e empresas das vagas do formato de resposta `**N. ⭐⭐⭐ Título da Vaga**`, e pular essas vagas na próxima execução.

### Personalizando as keywords

Edite a lista `KEYWORDS` no topo do `linkedin_jobs.py`:

```python
KEYWORDS = [
    "data engineer",
    "analytics engineer",
    "data analyst",
    # ...adicione as suas
]
```

Cada keyword gera 2 queries: Remoto Brasil + São Paulo (sem filtro de modalidade). Cargos de Manager/Head pulam o filtro de senioridade (já são sênior por definição).

### Personalizando os filtros

Edite a função `build_searches()` pra mudar:
- **Localização**: troque `"Brazil"` e `"São Paulo, Brazil"` pelas suas localizações alvo
- **Senioridade**: `f_E=4` significa Mid-Senior. Veja [Filtros da API do LinkedIn](#filtros-da-api-do-linkedin) abaixo
- **Tempo de publicação**: `f_TPR=r2592000` significa últimos 30 dias. Use `r604800` pra 7 dias, `r86400` pra 24h

### Personalizando o score heurístico

A função `heuristic_score()` no `linkedin_jobs.py` pontua cada vaga de 1-5 estrelas baseado em:
- **Stack técnico** (0-2 pontos): keywords de alta relevância (data engineer, AI engineer) vs. média relevância (data analyst, BI, SQL)
- **Senioridade** (0-2 pontos): keywords senior/lead/manager, ou assume pleno/sênior se não houver indicador
- **Localização** (0-1 ponto): remoto, Brasil, ou São Paulo

Edite as listas `high_skills` e `mid_skills` pra bater com seu perfil.

## Arquivos de Saída

Todos os arquivos são criados em `LINKEDIN_OUTPUT_DIR` (padrão: `~/linkedin-jobs/`):

| Arquivo | Descrição |
|------|-------------|
| `jobs_new.json` | Vagas novas pra o agente classificar. Inclui `heuristic_score` e `heuristic_reason` por vaga. Array vazio `[]` quando não há vagas novas. |
| `jobs.md` | Histórico de vagas legível pra humanos. Append-only — nunca remove entradas. Cada vaga é um bloco markdown com título, empresa, localização, modalidade, link e descrição curta. |
| `seen.json` | Estado de dedup. Contém `seen_ids` (IDs numéricos do LinkedIn) e `seen_keys` (strings normalizadas `título\|\|empresa`). |
| `keywords.json` | Tracking de yield por keyword. Cada keyword tem `total_runs`, `total_new`, `last_new`, `last_run`. Também rastreia keywords removidas. |

### Formato do jobs_new.json

```json
[
  {
    "id": "4429960220",
    "title": "Senior AI Engineer",
    "company": "Emma of Torre.ai",
    "location": "Brazil",
    "work_mode": "Remote",
    "date_label": "1 hour ago",
    "url": "https://www.linkedin.com/jobs/view/4429960220",
    "description": "Responsibilities and more: We are hiring...",
    "heuristic_score": 5,
    "heuristic_reason": "high stack, senior+, remote/BR"
  }
]
```

## Uso com um Agente LLM

O scraper é desenhado pra alimentar um agente LLM que classifica vagas e reporta ao usuário. Exemplo de prompt de agente:

```text
Você é um classificador de vagas.

1. Execute: python3 linkedin_jobs.py
2. Leia: ~/linkedin-jobs/jobs_new.json
3. Se estiver vazio, responda "Nenhuma vaga nova." e termine.
4. Para cada vaga, use o heuristic_score como ponto de partida.
   Reavalie apenas se heuristic_reason parecer errado.
5. Filtre apenas 3+ estrelas.
6. Ordene por data de publicação (mais recente primeiro).
7. Reporte neste formato:

   🔍 **N vagas novas** — data

   **1. ⭐⭐⭐⭐⭐ 🔥 Título da Vaga**
   Empresa | Local | Modalidade
   📅 Postada hoje | Match: justificativa curta
   [Ver vaga](url)
```

Salve a resposta do agente como um arquivo `.md` em `LINKEDIN_CRON_OUTPUT_DIR` pra que a próxima execução do scraper pule as vagas já reportadas.

### Exemplo de cron

```bash
# Rodar 3x ao dia: 8h, 13h, 18h
0 8,13,18 * * * LINKEDIN_OUTPUT_DIR=~/linkedin-jobs LINKEDIN_CRON_OUTPUT_DIR=~/.agente/outputs python3 ~/linkedin-job-scraper/linkedin_jobs.py
```

## Dashboard de Métricas

```bash
python3 linkedin_metrics.py
```

Exemplo de saída:

```
============================================================
  LinkedIn Job Scraper — Dashboard de Métricas
  20/06/2026 15:00
============================================================

## Base de dados
  IDs rastreados: 313
  Chaves título+empresa: 283
  Última atualização: 2026-06-20T15:01

## Yield por Keyword
  Keyword                         Runs  Yield     Última nova
  ------------------------------ ----- ------ ------------
  data engineer                      5    12 (2.4/run) 2026-06-20
  AI engineer                        5     8 (1.6/run) 2026-06-20
  BI manager                         5     0 (0 total) nunca

## Execuções recentes
        Data  Vagas Primeira vaga
  ------------ ------ ----------------------------------------
  2026-06-20 15-00      8 Senior Data Engineer
  2026-06-20 13-00      5 Data Tech Lead
  Total de execuções: 15

## Arquivo MD
  Vagas no MD: 313 (IDs únicos: 313)
  Tamanho: 97KB, 3630 linhas

============================================================
```

## Filtros da API do LinkedIn

Referência pra personalizar `build_searches()`:

| Filtro | Valores | Descrição |
|--------|--------|-------------|
| `f_TPR` | `r86400`, `r604800`, `r2592000` | Tempo de publicação: 24h, 7 dias, 30 dias |
| `f_E` | `1`-`6` | Experiência: 1=Intern, 2=Entry, 3=Associate, 4=Mid-Senior, 5=Director, 6=Executive |
| `f_WT` | `1`, `2`, `3` | Modalidade: 1=Presencial, 2=Remoto, 3=Híbrido |
| `sortBy` | `DD`, `R` | Ordenar por data decrescente, relevância |
| `start` | `0`, `25`, `50`, ... | Offset de paginação (25 por página) |

## Limitações

- **Apenas API Guest** — sem endpoints autenticados, sem status de candidatura, sem vagas salvas
- **Rate limiting** — o LinkedIn pode bloquear se você bater muito na API. O scraper usa 300ms entre páginas e 2s de backoff em retries
- **Parsing de HTML** — se o LinkedIn mudar a estrutura do HTML, os parsers de regex quebram. Abra uma issue se isso acontecer
- **Máx 8 vagas por execução** — pra ficar dentro do deadline de 4 minutos e evitar throttling da API. Ajuste `MAX_DETAIL` em `main()` se precisar de mais
- **Focado no Brasil** — filtros padrão focam em Brasil/São Paulo. Edite `build_searches()` pra outras regiões

## Como Funciona

```
┌─────────────────────────────────────────────────────────────┐
│                     SCRAPER (este repo)                      │
│                                                              │
│  1. Carrega seen.json (IDs + chaves)                        │
│  2. Lê últimos 3 outputs do agente (pula vagas reportadas)  │
│  3. Remove keywords improdutivas                            │
│  4. Busca na API Guest do LinkedIn (2 páginas × N queries)  │
│  5. Dedup tripla: ID + título/empresa + reportadas          │
│  6. Filtra: só Brasil/SP, sem júnior                        │
│  7. Busca detalhes em paralelo (3 threads, máx 8 vagas)     │
│  8. Salva: seen.json + keywords.json + jobs_new.json + jobs.md │
│                                                              │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼ jobs_new.json
┌─────────────────────────────────────────────────────────────┐
│                    AGENTE LLM (separado)                     │
│                                                              │
│  1. Lê jobs_new.json                                       │
│  2. Usa heuristic_score como ponto de partida              │
│  3. Reavalia casos borderline (2-4 estrelas)               │
│  4. Filtra pra 3+ estrelas                                 │
│  5. Ordena por data                                        │
│  6. Reporta ao usuário (Telegram, email, etc.)             │
│  7. Salva resposta como .md em LINKEDIN_CRON_OUTPUT_DIR    │
│                                                              │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼ próxima execução do scraper lê isso
                      (volta ao topo)
```

## Troubleshooting

**"Nenhuma vaga nova" toda execução**
- Verifique `seen.json` — pode ter crescido demais. O scraper exclui qualquer ID já visto. Pra resetar: delete `seen.json` e `jobs.md`.
- Verifique `keywords.json` — keywords podem ter sido removidas. Reset: delete `keywords.json`.

**API retorna resultados vazios**
- O LinkedIn pode estar limitando sua taxa. Espere 10-15 minutos.
- A API Guest pode estar fora do ar. Teste a URL direto no navegador: `https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=data+engineer&location=Brazil&start=0`
- Seu IP pode estar bloqueado. Tente uma VPN ou rede diferente.

**Vagas duplicadas aparecendo**
- Certifique-se de que `LINKEDIN_CRON_OUTPUT_DIR` está definido se você usa um agente. Sem isso, o scraper não sabe o que já foi reportado.
- Verifique se o formato da resposta do agente bate com `**N. ⭐⭐⭐ Título da Vaga**` (o regex espera estrelas).

## Contribuindo

1. Faça um fork
2. Crie sua branch de feature (`git checkout -b feature/foo`)
3. Commit suas mudanças (`git commit -am 'Add foo'`)
4. Push pra branch (`git push origin feature/foo`)
5. Crie um Pull Request

## Licença

MIT — veja [LICENSE](LICENSE).
