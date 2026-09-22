# F08b · Validar reprodutibilidade com Docker real

| | |
|---|---|
| **Esforço** | XS (menos de 15 min) |
| **Fase** | pré-produção |
| **Depende de** | [F08](F08-reprodutibilidade.md) |
| **Resolve** | Validação do critério de aceite de F08, que não pôde ser executado no ambiente de desenvolvimento (sem Docker disponível) |

## Problema

[F08](F08-reprodutibilidade.md) foi implementada (requirements.txt pinado,
`require-dbt-version`, imagens base fixadas por tag) mas o **critério de
aceite não foi executado** — o ambiente onde a implementação aconteceu não
tinha Docker instalado. As mudanças são coerentes na leitura do código, mas
não foram validadas rodando de verdade.

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

## Fora de escopo

- Qualquer mudança de código — esta fatia é **só validação**. Se algo
  falhar, o ajuste correto é reabrir a fatia original (F03/F05/F07/F08),
  não fazer patch aqui.

## Critério de aceite

Os 4 blocos de comando do escopo rodam sem erro, e o digest real está
travado no Dockerfile (não mais só a tag).
