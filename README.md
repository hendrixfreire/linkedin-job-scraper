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
- **Skill de setup guiado** — entrevista o usuário e configura tudo automaticamente

## Requisitos

- Python 3.8+
- Nenhuma dependência externa (apenas stdlib)
- [Hermes Agent](https://hermes-agent.nousresearch.com) (opcional, mas recomendado pra automação via cron e classificação com LLM)

## Guia Completo: Do Zero ao Cron Rodando

Este guia te leva do zero até um cron job rodando 3x ao dia que busca vagas no LinkedIn, classifica com LLM, e te manda no Telegram. São 6 passos.

### Passo 1 — Instalar o Hermes Agent

O Hermes Agent é o orquestrador que vai rodar o scraper em cron e classificar as vagas com LLM.

**Linux / macOS / WSL2 / Android (Termux):**

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
```

**Windows (PowerShell):**

```powershell
iex (irm https://hermes-agent.nousresearch.com/install.ps1)
```

O instalador cuida de tudo: Python, Node.js, ripgrep, ffmpeg, clone do repo, virtualenv e o comando global `hermes`.

Depois de instalar, configure um provider de LLM:

```bash
# Caminho fácil: Nous Portal (OAuth, sem chaves de API)
hermes setup --portal

# OU caminho completo (traga suas próprias chaves)
hermes model
```

Mais detalhes na [documentação oficial do Hermes](https://hermes-agent.nousresearch.com/docs/getting-started/quickstart).

### Passo 2 — Conectar o Telegram

Pra receber as vagas no Telegram, você precisa criar um bot e conectá-lo ao Hermes.

#### 2.1 Criar o bot com o BotFather

1. Abra o Telegram e procure por **@BotFather** (ou acesse [t.me/BotFather](https://t.me/BotFather))
2. Envie `/newbot`
3. Escolha um **nome de exibição** (ex: "Meu Scraper de Vagas")
4. Escolha um **username** único terminado em `bot` (ex: `meu_scraper_vagas_bot`)
5. O BotFather responde com seu **token de API**, no formato:
   ```
   123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
   ```
   **Guarde este token** — você vai usar no próximo passo.

#### 2.2 Descobrir seu User ID

1. No Telegram, procure por **@userinfobot** (ou acesse [t.me/userinfobot](https://t.me/userinfobot))
2. Envie qualquer mensagem
3. Ele responde com seu **User ID** (um número como `123456789`)
   **Guarde este ID** — você vai usar para autorizar o bot a falar com você.

#### 2.3 Conectar ao Hermes

Rode o wizard interativo:

```bash
hermes gateway setup
```

Selecione **Telegram** quando perguntado. O wizard vai pedir:
- **Bot Token**: o token do passo 2.1
- **Allowed Users**: seu User ID do passo 2.2

Ele escreve a configuração em `~/.hermes/.env` automaticamente.

#### 2.4 Iniciar o gateway

```bash
hermes gateway
```

O bot deve ficar online em segundos. **Mande uma mensagem no Telegram pro seu bot** pra confirmar que ele responde.

> 💡 Pra rodar o gateway em background permanentemente, veja o [guia de messaging](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram) do Hermes.

### Passo 3 — Baixar o script e a skill

Clone este repositório:

```bash
git clone https://github.com/hendrixfreire/linkedin-job-scraper.git
cd linkedin-job-scraper
```

Agora copie a skill de setup pro diretório de skills do Hermes:

```bash
# Criar o diretório de skills se não existir
mkdir -p ~/.hermes/skills

# Copiar a skill linkedin-job-setup
cp -r skills/linkedin-job-setup ~/.hermes/skills/

# Confirmar que copiou
ls ~/.hermes/skills/linkedin-job-setup/SKILL.md
```

A skill `linkedin-job-setup` é uma entrevista guiada que coleta suas preferências (cargo, senioridade, stack, localização, keywords) e configura o script automaticamente.

### Passo 4 — Rodar a entrevista de configuração (grill)

Abra um chat com seu bot no Telegram (ou rode `hermes` no terminal) e digite:

```
carregue a skill linkedin-job-setup e configure meu scraper de vagas
```

O agente vai te entrevistar com perguntas **uma de cada vez**:

1. **Nome** — qual nome usar no cabeçalho do arquivo de vagas
2. **Área principal** — Data Engineer, Data Analyst, BI Manager, AI/ML, etc.
3. **Senioridade alvo** — Sênior, Manager, Director, etc.
4. **Excluir júnior/pleno?** — sim/não
5. **Stack de alta relevância** — tecnologias e cargos que são match perfeito
6. **Stack de média relevância** — stack adjacente que você domina parcialmente
7. **Modalidades aceitas** — remoto, híbrido, presencial
8. **Localização** — Brasil remoto, São Paulo, outra cidade
9. **Keywords customizadas** — revisar/editar a lista gerada
10. **Frequência do cron** — 3x/dia, 2x/dia, 1x/dia

Pra cada pergunta, o agente mostra uma **resposta recomendada** em itálico. Se você concordar, é só confirmar. Se quiser mudar, digite sua resposta.

**Dica:** se quiser acelerar, diga "faz tudo e manda pra validar" — o agente aplica todas as recomendações padrão de uma vez e te mostra o resultado.

### Passo 5 — Script configurado e cron job criado

Depois da entrevista, o agente:

1. **Edita o `linkedin_jobs.py`** com suas configurações:
   - Lista `KEYWORDS` personalizada
   - `high_skills` e `mid_skills` no `heuristic_score()` baseado na sua stack
   - Filtros de localização (`build_searches`) e modalidade (`fetch_one`)
   - `USER_NAME` no header do MD
2. **Cria o cron job** no Hermes com:
   - Schedule escolhido (padrão: `0 8,13,18 * * *` = 3x/dia às 8h, 13h, 18h)
   - Prompt do agente classificador
   - Entrega no Telegram (deliver: origin)
3. **Roda o script uma vez** pra validar
4. **Mostra o dashboard de métricas** pra confirmar que tudo funcionou

### Passo 6 — Testes iniciais

Após a configuração, você deve ver no Telegram uma mensagem do bot com a primeira leva de vagas classificadas. Formato esperado:

```
🔍 7 vagas novas — 20/06/2026 15:00

1. ⭐⭐⭐⭐⭐ 🔥 Senior Data Engineer
Empresa | São Paulo, SP | Remoto
📅 Postada hoje | Match: stack BigQuery + Python bate direto
[Ver vaga](https://www.linkedin.com/jobs/view/...)

2. ⭐⭐⭐⭐ Data Tech Lead
...
```

Se não chegou nada em 10 minutos:

```bash
# Verificar o cron
hermes cron list

# Rodar manualmente
python3 ~/linkedin-job-scraper/linkedin_jobs.py

# Ver o JSON gerado
cat ~/linkedin-jobs/jobs_new.json

# Ver métricas
python3 ~/linkedin-job-scraper/linkedin_metrics.py
```

Pronto! A partir daqui o cron roda sozinho 3x ao dia. Você só precisa ler o Telegram.

## Configuração Manual (sem skill)

Se prefere configurar manualmente sem usar a skill, tudo é via variáveis de ambiente:

| Variável | Padrão | Descrição |
|----------|---------|-------------|
| `LINKEDIN_OUTPUT_DIR` | `~/linkedin-jobs` | Onde salvar os arquivos de saída |
| `LINKEDIN_USER_NAME` | `User` | Nome no cabeçalho do jobs.md |
| `LINKEDIN_CRON_OUTPUT_DIR` | _(desativado)_ | Diretório com os `.md` de resposta do agente (ativa dedup entre runs) |

Edite `linkedin_jobs.py` diretamente pra mudar keywords, filtros e heuristic_score.

## Arquivos de Saída

Criados em `LINKEDIN_OUTPUT_DIR` (padrão: `~/linkedin-jobs/`):

| Arquivo | Descrição |
|------|-------------|
| `jobs_new.json` | Vagas novas pro agente classificar. Inclui `heuristic_score` e `heuristic_reason`. Array vazio `[]` quando não há vagas. |
| `jobs.md` | Histórico legível. Append-only — nunca remove entradas. |
| `seen.json` | Estado de dedup. Contém `seen_ids` (IDs numéricos) e `seen_keys` (strings `título\|\|empresa`). |
| `keywords.json` | Tracking de yield por keyword. |

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

## Dashboard de Métricas

```bash
python3 linkedin_metrics.py
```

Exemplo:

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
  Total de execuções: 15

## Arquivo MD
  Vagas no MD: 313 (IDs únicos: 313)
  Tamanho: 97KB, 3630 linhas
```

## Filtros da API do LinkedIn

Referência pra customizar `build_searches()`:

| Filtro | Valores | Descrição |
|--------|--------|-------------|
| `f_TPR` | `r86400`, `r604800`, `r2592000` | Tempo de publicação: 24h, 7 dias, 30 dias |
| `f_E` | `1`-`6` | Experiência: 1=Intern, 2=Entry, 3=Associate, 4=Mid-Senior, 5=Director, 6=Executive |
| `f_WT` | `1`, `2`, `3` | Modalidade: 1=Presencial, 2=Remoto, 3=Híbrido |
| `sortBy` | `DD`, `R` | Ordenar por data decrescente, relevância |
| `start` | `0`, `25`, `50`, ... | Offset de paginação (25 por página) |

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
│                    AGENTE LLM (Hermes cron)                  │
│                                                              │
│  1. Lê jobs_new.json                                       │
│  2. Usa heuristic_score como ponto de partida              │
│  3. Reavalia casos borderline (2-4 estrelas)               │
│  4. Filtra pra 3+ estrelas                                 │
│  5. Ordena por data                                        │
│  6. Reporta ao usuário (Telegram)                          │
│  7. Salva resposta como .md em LINKEDIN_CRON_OUTPUT_DIR    │
│                                                              │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼ próxima execução do scraper lê isso
                      (volta ao topo)
```

## Limitações

- **Apenas API Guest** — sem endpoints autenticados, sem status de candidatura, sem vagas salvas
- **Rate limiting** — o LinkedIn pode bloquear se você bater muito na API. O scraper usa 300ms entre páginas e 2s de backoff em retries
- **Parsing de HTML** — se o LinkedIn mudar a estrutura do HTML, os parsers de regex quebram. Abra uma issue se isso acontecer
- **Máx 8 vagas por execução** — pra ficar dentro do deadline de 4 minutos. Ajuste `MAX_DETAIL` em `main()` se precisar de mais
- **Focado no Brasil** — filtros padrão focam em Brasil/São Paulo. Edite `build_searches()` pra outras regiões

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

**Bot do Telegram não responde**
- Verifique o token: `hermes gateway` deve mostrar logs sem erro
- Confirme que seu User ID está em `TELEGRAM_ALLOWED_USERS` em `~/.hermes/.env`
- Reinicie o gateway: `hermes gateway`

**Cron job não dispara**
- Verifique: `hermes cron list`
- Rode manualmente pra testar: `python3 ~/linkedin-job-scraper/linkedin_jobs.py`
- Cheque os logs: `~/.hermes/cron/output/<job_id>/`

## Contribuindo

1. Faça um fork
2. Crie sua branch de feature (`git checkout -b feature/foo`)
3. Commit suas mudanças (`git commit -am 'Add foo'`)
4. Push pra branch (`git push origin feature/foo`)
5. Crie um Pull Request

## Licença

MIT — veja [LICENSE](LICENSE).
