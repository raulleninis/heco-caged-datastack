# F02 · Concluir a migração para DuckDB-only

| | |
|---|---|
| **Esforço** | M (meio dia) |
| **Fase** | agora |
| **Depende de** | [F01](F01-destravar-o-clone.md) |
| **Resolve** | Achados A e N ([evidências E1](../revisao/03-evidencias.md#e1-o-mart-não-está-no-duckdb--está-no-postgres) e [E2](../revisao/03-evidencias.md#e2-o-projeto-dbt-não-faz-parse-sem-postgres)) |
| **Decisão associada** | [D01 — DuckDB-only ou manter Postgres?](../decisoes/D01-duckdb-only-ou-postgres.md) |

> ⚠️ **Leia a [decisão D01](../decisoes/D01-duckdb-only-ou-postgres.md) antes desta fatia.**
> Esta fatia assume que a resposta é "seguir para DuckDB-only", que é a direção que
> o `CLAUDE.MD` e o `README.md` já declaram. Se a decisão for outra, esta fatia muda
> de forma — mas a incoerência precisa acabar de um jeito ou de outro.

## Problema

A migração Postgres → DuckDB está **no meio do caminho**, e o repositório a
documenta como **concluída**:

- `CLAUDE.MD`: *"Postgres e Metabase foram removidos deliberadamente"* (passado).
- `README.md` Roadmap: `[x] remoção do Postgres e do Metabase`.
- `README.md` Roadmap, linha seguinte: `[ ] Ajustes finais de consolidação da migração`.

Enquanto isso, o mart mora numa tabela Postgres (`main_public.mart_caged_mensal_grupamento`),
o `.duckdb` tem 274 KB contendo só uma view, e o projeto dbt **nem faz parse** sem
`POSTGRES_HOST`.

Numa entrevista técnica, a pergunta é inevitável: *"cadê o Postgres que você diz ter removido?"*

## Os três pontos de acoplamento

Precisam cair **juntos** — remover um sem os outros quebra o projeto.

| # | Arquivo | O que prende |
|---|---|---|
| 1 | [`dbt/profiles.yml`](../../dbt/profiles.yml#L8-L13) | `extensions: postgres` + bloco `attach:` com 4 `env_var('POSTGRES_*')` |
| 2 | [`dbt/models/marts/mart_caged_mensal_grupamento.sql`](../../dbt/models/marts/mart_caged_mensal_grupamento.sql#L1-L5) | `config(database='postgres_db', schema='public')` |
| 3 | [`docker-compose.yml`](../../docker-compose.yml) | serviços `postgres` e `adminer`, `PREFECT_API_DATABASE_CONNECTION_URL`, dois `depends_on` |

## Escopo

1. **`profiles.yml`**: remover a extensão `postgres` e o bloco `attach:` inteiro.
   O perfil fica com `type: duckdb` e `path:` — nada mais.
2. **Mart**: remover `database=` e `schema=` do `config()`. O modelo passa a
   materializar no próprio `.duckdb`.
3. **`_marts.yml`**: corrigir a descrição, que hoje diz *"materializada no Postgres"*.
4. **Compose**: remover os serviços `postgres` e `adminer`, o volume `postgres_data`,
   e os `depends_on` que apontam para eles.
5. **Prefect**: trocar o backend de Postgres para SQLite, que é o que o `CLAUDE.MD`
   já afirma (*"Prefect 3.x — orquestração, backend SQLite"*). Isso exige um volume
   nomeado para persistir o SQLite entre restarts — **não deixe em disco efêmero**,
   ou você perde o histórico de runs a cada `docker compose down`.
6. **`.env` / `.env.example`**: remover `POSTGRES_USER` e `POSTGRES_PASSWORD`.
7. **Remover** `postgres/init-multiple-dbs.sh` e o diretório `postgres/`.
8. **Docs**: reconciliar `CLAUDE.MD` e o Roadmap do `README.md` com o estado real.

## Ponto de atenção: a restrição de concorrência do DuckDB

O próprio `CLAUDE.MD` documenta isso corretamente: DuckDB aceita **ou** vários
leitores read-only **ou** um único processo leitura-e-escrita. Depois desta fatia,
o `.duckdb` passa a conter o mart — ou seja, vira o alvo de leitura de qualquer
consumidor futuro (relatório, notebook, dashboard).

Isso **não é um bloqueio hoje** (não há consumidor persistente), mas é exatamente a
restrição que vai morder na [F10](F10-camada-analitica.md) e na
[F13](F13-migracao-nuvem.md). Registre a decisão em
[D03](../decisoes/D03-onde-guardar-os-dados.md) antes de ela virar um problema.

## Fora de escopo

- Trocar a materialização de `view` para `table` na staging ([F09](F09-testes-de-qualidade.md)).
- Qualquer correção de lógica de negócio ([F05](F05-corrigir-salario-medio.md)).

## Critério de aceite

```bash
# 1. dbt faz parse SEM nenhuma variável POSTGRES_*
docker run --rm -v "$PWD/dbt:/dbt" -v "$PWD/data:/data" \
  datastack-pipeline:latest dbt parse --project-dir /dbt --profiles-dir /dbt
# -> sucesso (hoje: "Env var required but not provided: 'POSTGRES_HOST'")

# 2. o mart existe DENTRO do .duckdb
docker run --rm -v "$PWD/data:/data" datastack-pipeline:latest python -c "
import duckdb
c = duckdb.connect('/data/warehouse/caged.duckdb', read_only=True)
print(c.execute('select table_name, table_type from information_schema.tables').fetchall())"
# -> deve listar mart_caged_mensal_grupamento como BASE TABLE

# 3. grep não encontra mais Postgres em lugar nenhum
grep -rni "postgres\|adminer\|metabase" --include="*.yml" --include="*.sql" \
  --include="*.md" --include="*.py" . | grep -v "^./docs/"
# -> só ocorrências históricas dentro de docs/
```

E os 24 registros do mart precisam bater com os de hoje — guarde o resultado de
`select * from mart_caged_mensal_grupamento order by 1,2` **antes** de começar e
compare depois. A migração não pode mudar número nenhum.
