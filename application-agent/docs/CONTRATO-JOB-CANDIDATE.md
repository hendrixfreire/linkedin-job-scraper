# Contrato JobCandidate v1

Este é o único ponto de integração entre coletores de vagas e o agente de candidatura. O coletor publica uma carga; o agente valida, importa idempotentemente e passa a ser dono do ciclo de candidatura.

## Envelope

```json
{
  "contract": "job-candidate",
  "schema_version": 1,
  "produced_at": "2026-07-19T12:00:00Z",
  "jobs": []
}
```

- `contract`: identificador fixo do domínio;
- `schema_version`: permite evoluir sem quebrar consumidores;
- `produced_at`: quando o lote foi produzido;
- `jobs`: candidatos de vaga, não candidaturas.

O schema canônico é [`../../contracts/job-candidate.v1.schema.json`](../../contracts/job-candidate.v1.schema.json).

## Identidade e idempotência

Cada vaga exige `source` + `source_job_id` + `source_url`. O agente usa `source_url` como chave idempotente local e preserva `source_job_id` como evidência do coletor. O mesmo lote pode ser entregue mais de uma vez sem duplicar vagas.

## Campos v1

| Campo | Obrigatório | Dono | Uso |
|---|---:|---|---|
| `source` | sim | coletor | Origem, por exemplo `linkedin` |
| `source_job_id` | sim | coletor | Identidade na origem |
| `source_url` | sim | coletor | URL HTTPS da vaga original |
| `title`, `company`, `location` | sim | coletor | Dados de apresentação e triagem |
| `work_mode` | não | coletor | `remote`, `hybrid`, `on_site` ou `unknown` |
| `posted_at`, `description` | não | coletor | Contexto de aderência |
| `source_score` | não | coletor | Score explicável de 0 a 100; não é o score final |
| `collected_at` | sim | coletor | Evidência temporal da coleta |

O coletor nunca publica dados do candidato, CV, respostas, cookie, sessão, URL de formulário já preenchido ou estado de submissão.

## Evolução

- Mudança compatível: campo opcional novo em v1.
- Mudança incompatível: publicar `schema_version: 2`, novo schema e adaptador explícito.
- O agente rejeita envelope desconhecido; falhar cedo evita uma fila silenciosamente corrompida.

## Exemplo

```json
{
  "contract": "job-candidate",
  "schema_version": 1,
  "produced_at": "2026-07-19T12:00:00Z",
  "jobs": [{
    "source": "linkedin",
    "source_job_id": "123456",
    "source_url": "https://www.linkedin.com/jobs/view/123456",
    "title": "Senior Data Engineer",
    "company": "Example Corp",
    "location": "Brazil",
    "work_mode": "remote",
    "posted_at": "2026-07-19",
    "description": "Python, SQL and data pipelines.",
    "source_score": 88,
    "collected_at": "2026-07-19T11:59:00Z"
  }]
}
```
