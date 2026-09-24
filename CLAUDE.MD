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
- Prefect 3.x — orquestração, backend SQLite com volume nomeado para persistência
- Pipeline executa em container não-root (UID 1000)
- Versões pinadas (`==`), sem pandas: prefect==3.8.0, dbt-core==1.12.0,
  dbt-duckdb==1.10.1, duckdb==1.5.5, py7zr==0.22.0 (ver F08). Imagem base
  `python:3.11.10-slim-bookworm` e `prefecthq/prefect:3.8.0-python3.11`
  também pinadas — nenhuma tag flutuante (`:latest`, `:slim`) no projeto.

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
- `pipeline/prefect.yaml` — deployment declarativo (cron schedule, work pool `default`)
- `pipeline/start.sh` — CMD do container: aguarda Prefect Server, aplica
  `prefect deploy --all`, inicia `prefect worker start --pool default`
- `pipeline/docker-entrypoint.sh` — ENTRYPOINT: alinha UID/GID do usuário
  `caged` com o dono real de `/data` e `/dbt` (bind mounts) antes de rodar
  qualquer comando, depois dropa privilégio via `gosu`
- `pipeline/flows/ingest_caged.py` — flows com varredura de lacunas:
  - `ingest_caged()` — consumido pelo worker via deployment agendado, varre
    últimos 6 meses procurando faltantes
  - `backfill_caged(ano)` — execução manual via CLI
    (`python flows/ingest_caged.py backfill <ano>`), varre ano inteiro
  - Ambos: baixam → extraem → deletam .7z → chamam `_transformar()`, que
    roda a staging UMA VEZ POR COMPETÊNCIA (`dbt run --select
    stg_caged_movimentacoes --vars '{"competencia_arquivo": "AAAAMM"}'`),
    depois materializa o mart uma vez e roda os testes (ver limitação de
    memória abaixo)
- `dbt/models/staging/_sources.yml` — declara `caged_raw.caged_movimentacoes`
  como source; `external_location` usa `read_csv_auto(...,
  all_varchar=true)` parametrizado com `{{ var('competencia_arquivo', '*') }}`
  (todo YAML de projeto dbt passa pelo Jinja renderer, não só `.sql`) —
  sem var, lê tudo via glob; com var, restringe a um arquivo. `freshness`
  baseada em `competencia_mov` convertida para data
- `dbt/models/staging/stg_caged_movimentacoes.sql` — materializada como
  `incremental` (`delete+insert`, `unique_key='competencia_mov'`), lê do
  source acima (tudo VARCHAR), faz CAST explícito por coluna, filtra uf=28
  (SE) e municipio=280480 (N. Sra. do Socorro), deriva `grupamento` e
  `subgrupamento`
- `dbt/tests/` — testes singulares: unicidade do grão do mart, coerência
  aritmética (`saldo_liquido = admissoes - desligamentos`), faixa plausível
  de salário (o teste que teria pego o bug de F05), salário individual
  (teto R$ 50.000 por admissão, pega outlier isolado na origem) e razão
  média/mediana (pega distorção moderada que a faixa absoluta deixa passar)
- `dbt/models/marts/mart_caged_mensal_grupamento.sql` — métricas por competência + grupamento:
  - `admissoes`, `desligamentos`, `saldo_liquido` (contagens)
  - `admissoes_com_salario_valido` (base do cálculo de salários)
  - `salario_mediano_admissao` (métrica robusta — referência)
  - `salario_medio_admissao` (para comparação com mediana)
  - `palma_index_admissao` (desigualdade: top 10% / bottom 40%)

## Comandos comuns
# Iniciar stack (Prefect Server + pipeline com deployment + worker)
docker compose up -d

# Backfill de um ano inteiro (manual, fora do schedule)
docker compose run --rm pipeline python flows/ingest_caged.py backfill 2026

# Disparar o ingest_caged do deployment agendado manualmente (sem esperar o cron)
docker compose exec pipeline prefect deployment run 'ingest-caged/caged-ingest-daily'

# Rodar dbt isoladamente — staging é incremental, uma competência por vez
docker compose run --rm pipeline dbt run --select stg_caged_movimentacoes \
  --vars '{"competencia_arquivo": "202608"}' --project-dir /dbt --profiles-dir /dbt
docker compose run --rm pipeline dbt run --select mart_caged_mensal_grupamento \
  --project-dir /dbt --profiles-dir /dbt
docker compose run --rm pipeline dbt test --project-dir /dbt --profiles-dir /dbt

# dbt run sem --select nem --vars roda a staging inteira via glob (*) — só
# use em dev/debug com poucas competências; nunca em produção (ver limitação
# de memória abaixo)

# Ver histórico de deployments no Prefect
curl -s http://localhost:4200/api/deployments/filter -X POST -H 'Content-Type: application/json' \
  -d '{"limit":10}' | python3 -m json.tool

## Gotchas da fonte de dados (PDET/Novo CAGED)
- Distribuído via FTP (ftp.mtps.gov.br), arquivo `.7z` (não `.zip`)
- Divulgação com ~1 mês de defasagem, sem dia fixo
  - Flow não assume data fixa: varre últimos 6 meses, procura lacunas
  - Se agosto atrasar (publicado em setembro), será ingerido no próximo run
- Colunas originais vêm acentuadas (ex. `salário`) — renomeadas para
  snake_case sem acento na staging
- `salario`, `valor_salario_fixo`, `horas_contratuais` usam vírgula decimal
  no arquivo bruto — precisam de `REPLACE(',', '.')` + `CAST` explícito
- Unidade de salário é heterogênea (hora, dia, semana, mês, etc)
  - Métricas de salário filtram só mensal (`unidade_salario_codigo = 5`)
  - Usam `valor_salario_fixo`, não `salario` genérico
  - Excluem valores ≤ 0 (significam "não informado" no CAGED declaratório)
  - Códigos observados em dados reais (202601-202607): 1,2,4,5,7,99 — 7 e 99
    não estão documentados no layout conhecido (1-6), mas aparecem nos dados
    (7 sempre valor=0; 99 majoritariamente 0, raramente não-zero). Não afetam
    o mart (filtra só código 5). Ver `_staging.yml` para accepted_values atual.

## Segredos
Tudo em `.env` (nunca commitado). Hoje só `PREFECT_HOST` (IP Tailscale).

## Fuso horário
O cron do `ingest_caged` é `"0 3 * * *"` — 3h UTC, meia-noite em Brasília.
Definido em `prefect.yaml` com `timezone: "America/Maceio"` para clareza.

## Limitação de memória — staging incremental é obrigatória, não opcional
Cada `.txt` bruto tem ~450-500MB (Brasil inteiro; filtramos ~1.500-2.000
linhas de N. Sra. do Socorro). Ler todas as competências de uma vez via
glob (`*.txt`) estoura memória — validado em runtime: só funcionava com
`mem_limit >= 3g`. O **servidor real de produção tem 830MB RAM total**
(~484MB disponível, ver D02) — nunca caberia processar tudo de uma vez.
Por isso a staging é `incremental`, processada uma competência por vez
pelo flow (pico de memória ~500MB, não ~3GB). **Não reverta para
`materialized='table'` com leitura via glob** sem resolver esse
dimensionamento primeiro.

## Retenção de dados brutos
Política D06: apagar dados regeneráveis da fonte (FTP).
- `.7z` original: **deletado imediatamente** após extração bem-sucedida
  - Não será reutilizado, economia imediata (~50% espaço)
- `.txt` extraído: staging já materializa incrementalmente (F09), lendo um
  arquivo por vez — tecnicamente já não depende mais do `.txt` após aquela
  execução específica processá-lo. Mas a deleção em si (F07 fase 2) ainda
  não foi implementada. Pendente.
- FTP é fonte de verdade pública: re-download é sempre possível (minutos)

## Permissões e containers
- Container roda como usuário `caged` (UID 1000 por padrão), não root
- `docker-entrypoint.sh` roda ANTES de qualquer comando e ajusta dinamicamente
  o UID/GID de `caged` para bater com o dono real de `/data` e `/dbt` no host
  — não exige que o host use UID 1000, nem `chown` manual
- Se o bind mount acabou de ser criado pelo Docker (dono ainda `root:root`,
  primeiro `up`), o entrypoint toma posse como `caged` diretamente

## Métricas de salário
Mart publica 4 métricas de salário (todas em admissões):
1. **`salario_mediano_admissao`** (PERCENTILE_DISC)
   - Métrica de referência, robusta a outlier
   - Padrão IBGE/PDET para estudos de mercado de trabalho
2. **`salario_medio_admissao`** (AVG)
   - Para comparação, mostra divergência (indicador de concentração)
3. **`palma_index_admissao`** (razão)
   - Desigualdade: média dos top 10% ÷ média dos bottom 40%
   - Interpretação: Palma > 1.5 indica desigualdade pronunciada
4. **`admissoes_com_salario_valido`** (contagem)
   - Base do cálculo: quantos registros entraram nas métricas
   - Contexto: NULL quando nenhum registro válido

Todas filtram:
- `unidade_salario_codigo = 5` (mensal, não hora/dia/semana)
- `valor_salario_fixo > 0` (excluem "não informado")

## Próximos passos (não implementado ainda)
Relatório mensal em PDF via CrewAI (múltiplos agentes: análise dos dados,
pesquisa de contexto na web, redação, revisão factual) + renderização
determinística (WeasyPrint). Regra de design: números nunca devem ser
calculados pelo LLM — só SQL determinístico, o agente interpreta/redige
em cima de fatos já calculados.
