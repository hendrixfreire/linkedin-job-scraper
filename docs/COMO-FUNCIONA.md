# Como funciona o Candidatura Agent

> Documento de orientação operacional. Última verificação: 13/07/2026.

## Resumo em uma frase

O sistema busca vagas no LinkedIn, grava tudo localmente, calcula aderência, prepara uma fila e mostra o estado num dashboard; o preenchimento real ainda está em `dry_run` e o envio automático permanece desligado.

## Onde cada coisa está

### 1. Projeto principal

```text
/Users/hendrixfreire/Projetos/candidatura-agent/
```

| Caminho | Função |
|---|---|
| `README.md` | Visão resumida do projeto |
| `docs/COMO-FUNCIONA.md` | Este mapa operacional |
| `docs/arquitetura.html` | Diagrama visual do fluxo |
| `config.json` | Chaves operacionais: meta mínima, ATS permitidos, Discord e flags de navegador/envio |
| `src/candidatura_agent/` | Código Python do sistema |
| `tests/` | Testes automatizados |
| `scripts/` | Comandos de execução |
| `data/` | Dados locais e privados; não entram no Git |
| `reports/` | Relatórios e capturas; não entram no Git |

### 2. Entrada de vagas e scraper

```text
/Users/hendrixfreire/.hermes/scripts/linkedin_jobs.py
/Users/hendrixfreire/Projetos/vagas_linkedin_new.json
```

- `linkedin_jobs.py`: consulta vagas no LinkedIn e deduplica resultados.
- `vagas_linkedin_new.json`: arquivo intermediário consumido pelo Candidatura Agent.

Wrapper do cron horário:

```text
/Users/hendrixfreire/.hermes/scripts/candidatura-hourly.sh
```

Ele executa o scraper e, em seguida, chama `scripts/run_hourly.sh` dentro do projeto.

### 3. Dados privados e estado

```text
/Users/hendrixfreire/Projetos/candidatura-agent/data/
```

| Arquivo/pasta | Conteúdo |
|---|---|
| `candidaturas.db` | SQLite: vagas, avaliações, candidaturas, eventos, feedback e respostas |
| `profile.json` | Perfil factual e respostas aprovadas para formulários |
| `run_control.json` | Resultado resumido da última execução horária |
| `browser-profile/` | Sessão persistente do Chromium/Playwright |

Esses itens estão no `.gitignore`. Código vai para Git; dados pessoais, sessões e histórico operacional ficam apenas na máquina.

### 4. CVs personalizados

Fonte factual única:

```text
/Users/hendrixfreire/Documents/CVs/cv_estruturado.md
```

Saída por empresa:

```text
/Users/hendrixfreire/Documents/CVs/<Empresa>/
```

Exemplo validado:

```text
/Users/hendrixfreire/Documents/CVs/Wellhub/cv-hendrix-freire-wellhub-senior-marketing-analytics-engineer.pdf
```

### 5. Relatórios e evidências

```text
/Users/hendrixfreire/Projetos/candidatura-agent/reports/
```

- `candidaturas-AAAA-MM-DD.md`: relatório diário.
- `screenshots/<vaga>/`: evidência visual das simulações.

### 6. Dashboard persistente

URL:

```text
http://127.0.0.1:8765
```

Código:

```text
src/candidatura_agent/dashboard.py
scripts/run_dashboard.sh
```

Serviço do macOS:

```text
/Users/hendrixfreire/Library/LaunchAgents/com.hendrix.candidatura-agent.plist
```

Logs:

```text
/tmp/candidatura-dashboard.out
/tmp/candidatura-dashboard.err
```

O `launchd` inicia o dashboard no login e o mantém vivo.

## Como as informações fluem

```text
Hermes Cron
   ↓
linkedin_jobs.py
   ↓
~/Projetos/vagas_linkedin_new.json
   ↓
hourly.py → ingest.py → policy.py
   ↓
data/candidaturas.db
   ├──→ dashboard.py → http://127.0.0.1:8765
   ├──→ daily_report.py → reports/candidaturas-AAAA-MM-DD.md
   └──→ fila qualificada
            ↓
       CV personalizado por vaga
            ↓
       browser.py + Playwright + adaptador do ATS
            ↓
       dry_run / blocked / submitted
            ↓
       volta ao SQLite e ao relatório
```

## O que cada módulo faz

| Módulo | Responsabilidade |
|---|---|
| `ingest.py` | Lê o JSON do scraper e evita duplicatas |
| `policy.py` | Calcula aderência e aplica filtros duros |
| `db.py` | Mantém o SQLite e a trilha de auditoria |
| `adapters.py` | Reconhece ATS e classifica campos do formulário |
| `browser.py` | Preenche formulários com Playwright e bloqueia perguntas inseguras |
| `hourly.py` | Orquestra ingestão, score, fila e navegador opcional |
| `dashboard.py` | Exibe estado e recebe feedback |
| `report.py` | Monta o texto do relatório diário |
| `daily_report.py` | Executa e salva o relatório |

## Automações ativas

| Automação | Agenda | Entrega | Estado verificado |
|---|---:|---|---|
| `linkedin-job-search` | 08:00, 13:00 e 18:00 | Telegram Home | Ativa |
| `candidatura-hourly` | de hora em hora, 08:30–18:30 | Local | Ativa |
| `candidatura-daily-report` | 20:15 | Esta conversa | Ativa |
| Dashboard via `launchd` | contínuo | localhost:8765 | Rodando |

Há duas rotinas que consultam o scraper: a antiga envia vagas ao Telegram e a nova alimenta o banco do agente. Elas estão separadas deliberadamente durante a calibração.

## O que já é automático

- busca e deduplicação de vagas;
- ingestão no SQLite;
- score e filtros;
- fila de qualificadas;
- dashboard e relatório diário;
- meta mínima de dez candidaturas por dia, sem teto diário;
- processamento de zero, uma ou várias vagas prontas em cada execução horária;
- notificação individual no Discord após cada envio confirmado;
- bloqueio de CAPTCHA, login, 2FA, ATS não autorizado e perguntas desconhecidas;
- reutilização de respostas já aprovadas.

## O que ainda NÃO é automático

- gerar CVs personalizados para todas as vagas da fila sem uma execução do agente;
- resolver todas as URLs externas do LinkedIn;
- preencher Lever e Ashby com validação real;
- enviar candidatura.

Configuração de segurança atual:

```json
{
  "daily_target_min": 10,
  "browser_enabled": false,
  "auto_submit": false,
  "notification_target": "discord:1526233025346666617:1526233025346666617"
}
```

Dez é uma meta mínima, não um máximo. Quando o navegador for liberado, cada ciclo processará todas as vagas prontas e qualificadas encontradas; isso pode produzir mais de uma candidatura por hora e mais de dez no dia.

A notificação usa a outbox `notifications` no SQLite. Um envio confirmado cria uma única entrada. `hermes send` entrega a mensagem no Discord e somente depois marca a entrada como entregue; falhas permanecem pendentes para retry na próxima execução.

Formato padrão:

```text
CANDIDATURA ENVIADA

Cargo: <cargo>
Empresa: <empresa>
Local: <local>
Aderência: <score>/100
Destaques: <motivos resumidos>
ATS: <plataforma>
Enviada em: <data/hora>

Resumo: <descrição curta>

Link da vaga: <URL externa>
Origem: <URL do LinkedIn, quando diferente>
```

Portanto, o cron horário busca e classifica, mas ainda não dispara candidaturas porque os dois gates continuam desligados. A simulação Wellhub foi uma execução controlada separada.

## Estado verificado em 13/07/2026

```text
47 vagas no banco
37 rejeitadas
9 qualificadas aguardando preparação
1 simulação concluída (Wellhub / Greenhouse)
0 candidaturas enviadas
0 feedbacks registrados
222 eventos de auditoria
21 testes passando
```

## Comandos para não se perder

```bash
cd ~/Projetos/candidatura-agent

# Resumo operacional sem exibir dados pessoais
./scripts/status.sh

# Abrir dashboard
open http://127.0.0.1:8765

# Rodar testes
.venv/bin/python -m pytest -q

# Executar apenas ingestão/classificação
./scripts/run_hourly.sh

# Gerar relatório
./scripts/run_report.sh

# Abrir o mapa visual
open docs/arquitetura.html
```

## Regra de segurança

`dry_run` pode preencher e anexar arquivos, mas não envia. `auto_submit` só deve ser habilitado depois de cinco simulações reais aprovadas e somente para ATS liberados. CAPTCHA, login, 2FA, pergunta nova ou inconsistência factual bloqueiam apenas aquela vaga.
