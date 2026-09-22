# CAGED Analytics — contexto para agentes de IA

## Objetivo
Pipeline de dados educacional/portfólio: ingestão, transformação e (em breve)
geração de relatório mensal automatizado sobre o mercado de trabalho formal
de Nossa Senhora do Socorro/SE, a partir dos microdados do Novo CAGED (PDET).

## Stack
- Ubuntu Server 24.04 LTS headless, acesso só via SSH (chave) + Tailscale
- Docker Compose (plugin v2, comando `docker compose`, sem hífen)
- DuckDB — único armazenamento de dado (staging + mart no mesmo arquivo .duckdb)
- dbt-core + dbt-duckdb — transformação e testes de qualidade
- Prefect 3.x — orquestração, backend SQLite (sem Postgres)

## Decisão de arquitetura importante
Postgres e Metabase foram removidos deliberadamente. Não recomendar
reintroduzi-los sem necessidade explícita — DuckDB sozinho é suficiente
porque não há consumidor com conexão persistente (ver restrição abaixo).

## Restrição técnica não óbvia
DuckDB só permite OU múltiplos leitores (read-only) OU um único processo
em leitura-e-escrita — nunca os dois ao mesmo tempo. Qualquer processo que
abrir o .duckdb pra leitura de forma persistente (ex.: um dashboard) impede
escrita em qualquer outro lugar até fechar a conexão.

## Estrutura
- `docker-compose.yml` — 2 serviços: prefect-server, pipeline
- `pipeline/flows/ingest_caged.py` — flows `ingest_caged` (cron diário) e
  `backfill_caged(ano)` (manual)
- `dbt/models/staging/stg_caged_movimentacoes.sql` — lê .txt bruto, filtra
  uf=28 (SE) e municipio=280480 (N. Sra. do Socorro), deriva `grupamento`
- `dbt/models/marts/mart_caged_mensal_grupamento.sql` — admissões/desligamentos/
  saldo por competência e grupamento

## Comandos comuns
docker compose up -d
docker compose run --rm pipeline dbt run --project-dir /dbt --profiles-dir /dbt
docker compose run --rm pipeline dbt test --project-dir /dbt --profiles-dir /dbt
docker compose run --rm pipeline python -c "from flows.ingest_caged import backfill_caged; backfill_caged(2026)"

## Gotchas da fonte de dados (PDET/Novo CAGED)
- Distribuído via FTP (ftp.mtps.gov.br), arquivo `.7z` (não `.zip`)
- Divulgação com 1 mês de defasagem, sem dia fixo — o flow checa existência
  no FTP antes de assumir que a competência não saiu
- Colunas originais vêm acentuadas (ex. `salário`) — renomeadas para
  snake_case sem acento na staging
- `salario`, `valor_salario_fixo`, `horas_contratuais` usam vírgula decimal
  no arquivo bruto — precisam de `REPLACE(',', '.')` + `CAST` explícito

## Segredos
Tudo em `.env` (nunca commitado). Hoje só `PREFECT_HOST` (IP Tailscale).

## Fuso horário
O cron do `ingest_caged` é `"0 3 * * *"` — 3h UTC, meia-noite em Brasília.
Definido em `prefect.yaml` com `timezone: "America/Maceio"` para clareza.

## Próximos passos (não implementado ainda)
Relatório mensal em PDF via CrewAI (múltiplos agentes: análise dos dados,
pesquisa de contexto na web, redação, revisão factual) + renderização
determinística (WeasyPrint). Regra de design: números nunca devem ser
calculados pelo LLM — só SQL determinístico, o agente interpreta/redige
em cima de fatos já calculados.
