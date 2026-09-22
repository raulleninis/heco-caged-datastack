# Evidências — como reproduzir cada achado

> Documento de apoio à revisão de 21/09/2026. Todo achado aqui foi obtido
> **executando o sistema**, não lendo código. Os comandos são reproduzíveis.

---

## E1. O mart não está no DuckDB — está no Postgres

```bash
docker exec postgres psql -U "$(grep POSTGRES_USER .env | cut -d= -f2)" \
  -d warehouse -c "\dt *.*" | grep mart
```

```
 main_public | mart_caged_mensal_grupamento | table | hecodata
```

E o arquivo DuckDB contém **apenas a view de staging**:

```bash
docker run --rm -v "$PWD/data:/data" datastack-pipeline:latest python -c "
import duckdb
c = duckdb.connect('/data/warehouse/caged.duckdb', read_only=True)
print(c.execute('select table_schema, table_name, table_type from information_schema.tables').fetchall())"
```

```
[('main', 'stg_caged_movimentacoes', 'VIEW')]
```

O `.duckdb` tem 274 KB — não há dado materializado nele.

**Detalhe extra:** o schema criado no Postgres é `main_public`, **não** `public`
como pede `config(schema='public')`. O dbt-duckdb concatena
`<schema_do_duckdb>_<schema_configurado>`.

> **Enquadramento correto:** a migração Postgres → DuckDB-only está **em andamento**,
> não é um erro de rota. O problema não é a direção, é o **estado de registro**:
> o repositório documenta o destino como se já fosse o presente.
>
> - `CLAUDE.MD` afirma no passado: *"Postgres e Metabase foram removidos deliberadamente"*.
> - `README.md` marca `[x] Simplificação da arquitetura: remoção do Postgres e do Metabase`.
> - `README.md` marca, **na linha seguinte**, `[ ] Ajustes finais de consolidação da migração`.
>
> As duas últimas se contradizem. A descrição em
> [_marts.yml](../../dbt/models/marts/_marts.yml) — *"materializada no Postgres"* —
> é a única que descreve o estado real de hoje.

---

## E2. O projeto dbt não faz parse sem Postgres

```bash
docker run --rm -v "$PWD/dbt:/dbt" -v "$PWD/data:/data" \
  datastack-pipeline:latest dbt parse --project-dir /dbt --profiles-dir /dbt
```

```
Running with dbt=1.12.0
[ERROR]: Encountered an error:
Parsing Error
  Env var required but not provided: 'POSTGRES_HOST'
```

O acoplamento ao Postgres é **estrutural** ([profiles.yml:11](../../dbt/profiles.yml#L11)),
não uma sobra cosmética. Sem Postgres o projeto não compila — muito menos roda.

Isso dimensiona o trabalho restante da migração: não basta apagar serviços do
`docker-compose.yml`. São **três pontos de acoplamento**, e todos precisam cair juntos:

| # | Arquivo | Linha | O que prende ao Postgres |
|---|---|---|---|
| 1 | [dbt/profiles.yml](../../dbt/profiles.yml#L8-L13) | 8-13 | `extensions: postgres` + bloco `attach:` com `env_var('POSTGRES_HOST')` |
| 2 | [dbt/models/marts/mart_caged_mensal_grupamento.sql](../../dbt/models/marts/mart_caged_mensal_grupamento.sql#L1-L5) | 1-5 | `config(database='postgres_db', schema='public')` |
| 3 | [docker-compose.yml](../../docker-compose.yml) | 3-28, 47-58 | serviços `postgres` e `adminer`; `PREFECT_API_DATABASE_CONNECTION_URL`; `depends_on` |

Enquanto o nº 1 existir, **nenhum comando dbt roda sem as variáveis `POSTGRES_*`** —
inclusive `dbt parse`, `dbt compile` e `dbt deps`, que nem chegam a tocar no banco.

Ver a fatia [F02](../fatias/F02-concluir-migracao-duckdb.md) para o roteiro de corte.

---

## E3. Clone limpo + `docker compose up -d` falha

Três passos encadeados:

```bash
docker compose --env-file /dev/null config 2>&1 | grep warning
```
```
warning: The "POSTGRES_USER" variable is not set. Defaulting to a blank string.
warning: The "POSTGRES_PASSWORD" variable is not set. Defaulting to a blank string.
warning: The "PREFECT_HOST" variable is not set. Defaulting to a blank string.
```

```bash
docker run --rm -e POSTGRES_USER= -e POSTGRES_PASSWORD= postgres:16-alpine
```
```
Error: Database is uninitialized and superuser password is not specified.
```

E como `prefect-server` e `pipeline` declaram
`depends_on: postgres: condition: service_healthy`, **a stack inteira não sobe**.

O README manda `cp .env.example .env`, mas **`.env.example` não existe no repositório**
(`git ls-files` confirma). Efeito colateral: `PREFECT_UI_API_URL` vira `http://:4200/api`.

---

## E4. O agendamento nunca existiu

```bash
curl -s -X POST http://localhost:4200/api/deployments/filter \
  -H 'Content-Type: application/json' -d '{"limit":10}'
```
```
[]
```

Zero deployments. O único flow run da história do projeto:

```bash
curl -s -X POST http://localhost:4200/api/flow_runs/filter \
  -H 'Content-Type: application/json' -d '{"limit":5,"sort":"START_TIME_DESC"}'
```
```
name: stimulating-kittiwake | created: 2026-07-28 | parameters: {"ano": 2026} | COMPLETED
```

Foi um `backfill_caged(2026)` **manual**, em 28/07/2026. Desde então, nada.

**Causa raiz:** o `.serve(cron="0 3 * * *")` está dentro de
`if __name__ == "__main__"` ([ingest_caged.py:145-146](../../pipeline/flows/ingest_caged.py#L145-L146)),
e o serviço `pipeline` não tem `CMD` que o execute.

---

## E5. O container `pipeline` sequer existe

```bash
docker compose ps -a
```
```
NAME             IMAGE                        STATUS
adminer          adminer:latest               Up 2 hours
postgres         postgres:16-alpine           Up 2 hours (healthy)
prefect-server   prefecthq/prefect:3-latest   Up 2 hours
```

A imagem foi construída (`datastack-pipeline:latest`, 1,19 GB), mas nenhum
container dela está criado. Logo `restart: unless-stopped` é inócuo.

E se subisse, entraria em crash loop:

```bash
docker inspect datastack-pipeline:latest \
  --format 'Cmd={{.Config.Cmd}} Entrypoint={{.Config.Entrypoint}} User=[{{.Config.User}}]'
```
```
Cmd=[python3] Entrypoint=[] User=[]
```

`Cmd=[python3]` é herdado do `python:3.11-slim` — sem TTY o processo sai na hora,
e `restart: unless-stopped` o reinicia para sempre.

---

## E6. `salario_medio_admissao` está errado — mistura unidades de salário

Sintoma no mart: **202603 / Construção = R$ 7.265,68**, contra ~R$ 1.900 nos
demais meses do mesmo grupamento.

```bash
docker run --rm -v "$PWD/data:/data" datastack-pipeline:latest python -c "
import duckdb
print(duckdb.connect().execute('''
select unidadesaláriocódigo, count(*) n,
       round(avg(cast(replace(salário, ',', '.') as double)),2) media
from read_csv_auto('/data/raw/extraido/CAGEDMOV202603.txt', delim=';', union_by_name=true)
where uf=28 and município=280480 and seção=\'F\' and saldomovimentação=1
group by 1 order by 1''').fetchall())"
```

```
unidade=1 (HORA):  1 registro,  salário 356.620,00
unidade=5 (MÊS):  66 registros, média    1.972,43
```

A aritmética fecha exatamente com o valor do mart:

```
(66 × 1.972,43 + 356.620) ÷ 67 = 7.265,67
```

São **duas falhas somadas**:
1. a média é calculada sobre unidades heterogêneas (hora, dia, mês… misturadas);
2. não há nenhum tratamento de outlier/valor absurdo vindo da fonte.

Um único registro corrompe a métrica principal de um grupamento inteiro.

---

## E7. Defasagem de 2 competências + bug de janela

O FTP já publicou até **202607**; o projeto ingeriu até **202605**.

```bash
docker run --rm datastack-pipeline:latest python -c "
from ftplib import FTP
f = FTP('ftp.mtps.gov.br', timeout=25); f.login()
f.cwd('/pdet/microdados/NOVO CAGED/2026'); print(sorted(f.nlst()))"
```
```
['202601', '202602', '202603', '202604', '202605', '202606', '202607']
```

`competencia_alvo()` ([ingest_caged.py:22-28](../../pipeline/flows/ingest_caged.py#L22-L28))
devolve **sempre o mês anterior** — hoje (21/09/2026), `202608`, que ainda não saiu:

```
202608 -> indisponivel: 550 The system cannot find the file specified.
```

**O bug:** 202607 já está disponível, mas o flow diário nunca mais vai pedi-lo.
Em outubro ele passará a pedir 202609. **Qualquer competência que escape da janela
do mês é perdida para sempre** — não há varredura de lacunas.

Agravante: o CLAUDE.MD afirma defasagem de "1 mês". A defasagem real observada
é de ~1,5 a 2 meses, o que torna a janela de 1 mês estruturalmente frágil.

---

## E8. Raw de 2,5 GB, sem retenção, arquivos pertencentes a root

```bash
du -sh data/raw && ls -la data/raw/extraido/
```
```
2,5G    data/raw
-rw-r--r-- 1 root root 448833720 CAGEDMOV202601.txt
-rw-r--r-- 1 root root 469941913 CAGEDMOV202602.txt
... (5 arquivos, ~450 MB cada)
```

Os containers rodam como root (`docker run ... id` → `uid=0(root)`) e escrevem no
bind mount `./data`, então os arquivos ficam `root:root` no host. Nenhuma rotina
de limpeza: **+450 MB por competência, indefinidamente.**

---

## E9. Deriva de versões e dependência morta

```bash
docker run --rm datastack-pipeline:latest pip list | grep -iE "prefect|dbt|duckdb|pandas|py7zr"
```
```
dbt-core    1.12.0     dbt-duckdb  1.10.1     duckdb   1.5.5
pandas      3.0.5      prefect     3.8.0      py7zr    0.22.0
```

`requirements.txt` usa faixas largas. `pandas>=2.0` deixou entrar **pandas 3.0.5**
(major com breaking changes) — e:

```bash
grep -rn "pandas" --include="*.py" .
```
```
(nenhuma ocorrência)
```

**pandas nunca é importado.** É peso morto numa imagem de 1,19 GB.

Além disso, `_staging.yml` usa `accepted_values:` com bloco `arguments:`, sintaxe
que só existe a partir do **dbt 1.10** — mas `requirements.txt` aceita
`dbt-core>=1.8`. Um build que resolva para 1.8/1.9 quebra o parse dos testes.

---

## E10. `caged_exclude_columns` é maquinário morto

```bash
grep -rn "caged_exclude_columns" --include="*.yml" --include="*.sql" --include="*.py" .
```
```
dbt/models/staging/stg_caged_movimentacoes.sql:3
```

Só a própria declaração. A var nunca é definida em `dbt_project.yml` nem passada
via `--vars`. O laço de exclusão em
[stg_caged_movimentacoes.sql:61](../../dbt/models/staging/stg_caged_movimentacoes.sql#L61)
nunca exclui nada.
