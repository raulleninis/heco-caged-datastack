# F08b · Validar com Docker real (F08 + F09 + correções de revisão)

| | |
|---|---|
| **Esforço** | S (menos de 1 h) |
| **Fase** | pré-produção |
| **Depende de** | [F08](F08-reprodutibilidade.md), [F09](F09-testes-de-qualidade.md) |
| **Resolve** | Validação dos critérios de aceite de F08 e F09, e das correções de F03/F05/F07 feitas na revisão de código — nada disso rodou com Docker de verdade |

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
