# F03 · Fazer o agendamento existir de verdade

| | |
|---|---|
| **Esforço** | M (meio dia) |
| **Fase** | agora |
| **Depende de** | [F02](F02-concluir-migracao-duckdb.md), [F08](F08-reprodutibilidade.md) |
| **Resolve** | Achados B, C, I ([evidências E4](../revisao/03-evidencias.md#e4-o-agendamento-nunca-existiu) e [E5](../revisao/03-evidencias.md#e5-o-container-pipeline-sequer-existe)) |

## Problema

O `README.md` marca `[x] Agendamento via Prefect` como concluído. **Não há agendamento.**

```
POST /api/deployments/filter  ->  []
```

Zero deployments. O único flow run da história do projeto foi um
`backfill_caged(2026)` **manual**, em 28/07/2026. Desde então o pipeline nunca rodou —
é por isso que os dados param em 202605 enquanto o FTP já publicou até 202607.

São **três falhas encadeadas**:

1. O `.serve(cron="0 3 * * *")` está dentro de `if __name__ == "__main__"`
   ([ingest_caged.py:145](../../pipeline/flows/ingest_caged.py#L145)) — só executa se
   alguém rodar o arquivo como script.
2. O `Dockerfile` **não tem `CMD`**. A imagem herda `Cmd=[python3]` do
   `python:3.11-slim`, que sem TTY sai imediatamente.
3. O container `pipeline` **nem existe** (`docker compose ps -a` lista só postgres,
   adminer e prefect-server), então o `restart: unless-stopped` nunca teve chance de agir.

O detalhe cruel: se você simplesmente subir o serviço hoje, ele entra em
**crash loop infinito** — `python3` sai na hora, `restart: unless-stopped` reinicia.

## Escopo

1. Adicionar `CMD` explícito ao `Dockerfile` apontando para o processo que serve os flows.
2. Decidir o modelo de execução ([D02](../decisoes/D02-modelo-de-execucao.md)):
   - **`.serve()`** — processo longo, simples, sem work pool. Adequado a 1 flow e 1 máquina.
   - **worker + work pool** — mais peças, mas é o padrão que aparece em vaga de dados
     e o que escala para a nuvem.
3. Criar o deployment de fato, versionado (`prefect.yaml` ou `flow.from_source(...).deploy(...)`),
   não por comando manual — um deployment que só existe na máquina do autor não é reprodutível.
4. Garantir persistência: se o backend do Prefect virou SQLite na [F02](F02-concluir-migracao-duckdb.md),
   ele precisa de volume nomeado, ou o histórico de runs some a cada `down`.
5. Remover `restart: unless-stopped` de qualquer serviço que não seja um processo longo de verdade.

## Armadilha de fuso horário

`cron="0 3 * * *"` roda às 3h **no fuso do container**, que por padrão é UTC —
ou seja, **meia-noite em Brasília**. Se a intenção era "de madrugada, horário local",
defina `TZ=America/Maceio` no serviço ou use o parâmetro de timezone do Prefect.
Hoje isso é invisível porque nada roda.

## Fora de escopo

- Descomentar as chamadas `run_dbt` ([F04](F04-religar-dbt-no-flow.md)).
- Alerta de falha ([F11](F11-observabilidade.md)).

## Critério de aceite

```bash
docker compose up -d
sleep 30
curl -s -X POST http://localhost:4200/api/deployments/filter \
  -H 'Content-Type: application/json' -d '{"limit":10}' | python3 -m json.tool
# -> pelo menos 1 deployment, com schedule ativo
```

E, depois de `docker compose down && docker compose up -d`, o deployment **continua lá** —
sem nenhum comando manual de re-registro.
