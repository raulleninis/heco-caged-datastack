# F08b · Validar com Docker real (F08 + F09 + correções de revisão)

| | |
|---|---|
| **Status** | ✅ Concluída (22/09/2026) |
| **Esforço** | S (menos de 1 h) |
| **Fase** | pré-produção |
| **Depende de** | [F08](F08-reprodutibilidade.md), [F09](F09-testes-de-qualidade.md) |
| **Resolve** | Validação dos critérios de aceite de F08 e F09, e das correções de F03/F05/F07 feitas na revisão de código — nada disso rodou com Docker de verdade |

## Resultado

Todos os 8 itens do escopo foram executados com Docker Desktop real (backfill
de 202601-202607, 3.1GB de dados brutos do FTP público). **4 bugs reais**
foram encontrados — nenhum visível por leitura de código — e corrigidos
reabrindo as fatias originais, conforme "fora de escopo" previa:

1. **CRÍTICO** — `/data/warehouse` não existia; `dbt run` falhava com "No
   such file or directory" num clone limpo. Corrigido em
   `docker-entrypoint.sh` (F07).
2. **CRÍTICO** — staging lendo todas as competências via glob estourava
   memória (só funcionava com `mem_limit >= 3g`; servidor real tem 830MB
   RAM total). Staging convertida para `incremental`, processada uma
   competência por vez (F09).
3. `mart_caged_mensal_grupamento.sql` — `avg(case when x >= max(p90)...)`:
   DuckDB não permite agregação aninhada. Bug introduzido na correção do
   bug crítico de F05 nesta mesma sessão; só apareceu na execução, não no
   parse. Corrigido com JOIN por linha antes da agregação (F05).
4. `test_faixa_salario_plausivel.sql` — teto de R$20.000 não pegava o caso
   de referência (R$7.265,68, o próprio bug histórico de F05) — só
   descoberto fazendo o "teste do teste" do item 8 abaixo. Teto corrigido
   para R$6.000, validado contra a faixa real observada (F09).

Também corrigido, sem ser bug: `accepted_values` de `unidade_salario_codigo`
estava incompleto (dados reais têm códigos 7 e 99, não documentados no
layout de 1-6 conhecido).

**Digest travado**: `python:3.11.10-slim-bookworm@sha256:840e180e...` e
`prefecthq/prefect:3.8.0-python3.11@sha256:336db9a1...` (capturados via
`docker inspect`, commitados no Dockerfile e docker-compose.yml).

**Validação end-to-end**: deployment disparado via `prefect deployment run`
rodou através do worker real do container, `competencias_ja_ingeridas()`
detectou as 7 competências corretamente, checou 202608/202609 no FTP
(nenhuma publicada) e encerrou limpo — F03 e F06 confirmadas em produção
real, não só em teoria. 21/21 `dbt test` passam.

## Problema

[F08](F08-reprodutibilidade.md) e [F09](F09-testes-de-qualidade.md) foram
implementadas, assim como correções de uma revisão de código sobre F03/F05/F07
(bug crítico no mart, permissões dinâmicas, `prefect deploy` real) — mas
**nada disso rodou** no ambiente onde foi implementado, que não tinha Docker
instalado. As mudanças são coerentes na leitura do código, mas não foram
validadas executando de verdade.

Em especial, F09 reescreveu a leitura do CSV bruto (source declarado,
`all_varchar=true`, CAST explícito por coluna) — uma mudança estrutural que
precisa ser validada contra dados reais para garantir que os números não
mudaram (só a forma de leitura).

Além disso, o Dockerfile hoje pina `python:3.11.10-slim-bookworm` só por
**tag**, não por **digest** — porque capturar o digest exige um primeiro
build real, que não pôde ser feito.

## Escopo

1. Rodar o critério de aceite completo de F08:
   ```bash
   docker build --no-cache -t teste ./pipeline
   docker run --rm teste pip list | grep -iE "prefect|dbt|duckdb|py7zr"
   # -> prefect 3.8.0, dbt-core 1.12.0, dbt-duckdb 1.10.1, duckdb 1.5.5, py7zr 0.22.0

   docker run --rm teste pip list | grep -i pandas
   # -> vazio

   docker images teste --format '{{.Size}}'
   # -> menor que 1,19 GB (tamanho antes de F08)
   ```
2. Capturar o digest real da imagem base e travá-lo no Dockerfile:
   ```bash
   docker inspect --format='{{index .RepoDigests 0}}' python:3.11.10-slim-bookworm
   # substituir a linha FROM por:
   # FROM python:3.11.10-slim-bookworm@sha256:<digest capturado>
   ```
3. Validar a stack completa (valida de quebra também as correções de F03/F07
   feitas na revisão, que também não foram testadas em runtime):
   ```bash
   docker compose up -d --build
   docker compose ps            # prefect-server e pipeline "Up"/"healthy"
   docker compose logs pipeline # confirma: entrypoint ajustou permissões,
                                 # start.sh aplicou prefect deploy, worker subiu
   ```
4. Confirmar que o bind mount `./data` fica com o dono correto (não root),
   sem precisar de `chown` manual — testar em especial o cenário de
   primeiro `up` (diretório `data/` ainda não existe no host).
5. Disparar um `backfill_caged` de teste e confirmar que o mart bate com os
   números esperados após a correção do bug crítico de F05 (ver histórico
   de revisão — `admissoes`/`desligamentos`/`saldo_liquido` tinham regredido).
6. Rodar `dbt run` + `dbt test` completo (critério de aceite de F09):
   ```bash
   docker compose run --rm pipeline dbt run --project-dir /dbt --profiles-dir /dbt
   docker compose run --rm pipeline dbt test --project-dir /dbt --profiles-dir /dbt
   # -> todos os testes passam, incluindo os 3 singulares novos em dbt/tests/
   ```
7. Confirmar que a mudança de leitura (source com `all_varchar=true` + CAST
   explícito) não alterou nenhum valor em relação à leitura anterior
   (inferência automática do DuckDB) — comparar contagens e agregados do
   mart antes/depois se houver uma cópia do `.duckdb` anterior à mudança.
8. Teste do teste — confirmar que os testes novos realmente pegam defeito:
   ```sql
   -- reintroduza um registro com unidade_salario_codigo=1 (hora) e
   -- valor_salario_fixo=356620.00 na base, rode dbt test
   -- -> test_faixa_salario_plausivel DEVE falhar
   ```

## Fora de escopo

- Qualquer mudança de código — esta fatia é **só validação**. Se algo
  falhar, o ajuste correto é reabrir a fatia original (F03/F05/F07/F08/F09),
  não fazer patch aqui.

## Critério de aceite

Os 8 blocos de comando do escopo rodam sem erro, o digest real está travado
no Dockerfile (não mais só a tag), e o teste de faixa de salário falha
quando o defeito é reintroduzido deliberadamente.
