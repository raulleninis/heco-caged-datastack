# F01 · Destravar o clone

| | |
|---|---|
| **Esforço** | XS (menos de 15 min) |
| **Fase** | agora |
| **Depende de** | — |
| **Resolve** | Achado M ([evidência E3](../revisao/03-evidencias.md#e3-clone-limpo--docker-compose-up--d-falha)) |

## Problema

Hoje, um `git clone` seguido de `docker compose up -d` **falha na primeira tentativa**.
O README instrui `cp .env.example .env`, mas esse arquivo não existe no repositório.
Sem ele, `POSTGRES_PASSWORD` resolve para string vazia, o Postgres se recusa a
inicializar, e como os outros serviços dependem dele via `service_healthy`, nada sobe.

Para um projeto que é **vitrine profissional**, esse é o pior erro possível: é o
primeiro comando que um avaliador digita.

## Escopo

1. Criar `.env.example` versionado, com todas as variáveis que o `docker-compose.yml`
   referencia, valores de exemplo seguros e um comentário por variável.
2. Dar valores padrão no compose para as variáveis que podem ter um
   (`${POSTGRES_USER:-caged}`), e deixar falhar com mensagem clara as que não podem
   (`${POSTGRES_PASSWORD:?defina POSTGRES_PASSWORD no .env}`).
3. Tornar `PREFECT_HOST` opcional com padrão `localhost`, para que o clone funcione
   sem Tailscale.
4. Corrigir o README para que o caminho descrito seja o caminho que funciona.

## Fora de escopo

- Remover o Postgres (isso é [F02](F02-concluir-migracao-duckdb.md)).
- Qualquer mudança em modelos dbt ou no flow.

## Critério de aceite

```bash
git clone <repo> /tmp/teste && cd /tmp/teste
cp .env.example .env
docker compose up -d
docker compose ps        # todos os serviços esperados em "Up"/"healthy"
```

Sem editar nenhum arquivo entre o `cp` e o `up`.

## Observação sobre a ordem

Esta fatia vem antes de [F02](F02-concluir-migracao-duckdb.md) de propósito: é mais
barato garantir que o estado atual sobe do que debugar um clone quebrado no meio de
uma migração de arquitetura.
