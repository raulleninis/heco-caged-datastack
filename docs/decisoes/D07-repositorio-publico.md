# D07 · Quando abrir o repositório

**Status:** decidida (21/09/2026) · **Bloqueia:** [F10](../fatias/F10-camada-analitica.md) · **Urgência:** média

## Contexto

O projeto é vitrine — **vai ser público**. A pergunta é *quando*, e *o que limpar antes*.

## Checklist de segurança antes de abrir

| item | estado |
|---|---|
| `.env` no `.gitignore` | ✅ correto |
| `.env` no histórico do git | ✅ **nunca foi commitado** (verificado: `git log --all -- .env` vazio) |
| `data/` ignorado | ✅ correto |
| Senha em arquivo versionado | ⚠️ `profiles.yml` tem `password=...` via `env_var` — **não vaza valor**, mas expõe o desenho |
| `PREFECT_HOST` (IP Tailscale) | ⚠️ está só no `.env`; confirme que não vazou em log ou print |
| `dbt/logs/` ignorado | ✅ correto — logs de dbt podem conter string de conexão |

**O básico está certo.** O `.gitignore` foi bem feito desde o primeiro commit, e o
`.env` nunca entrou no histórico. Não há vazamento a remediar.

> Se a [D01](D01-duckdb-only-ou-postgres.md) for DuckDB-only, os dois itens ⚠️
> desaparecem junto com o Postgres.

## A questão dos microdados

A [F10](../fatias/F10-camada-analitica.md) propõe versionar uma **amostra** dos dados
para destravar o "clone e rode". Antes: confirme os termos de uso do PDET para
redistribuição. São dados públicos, mas *público* ≠ *redistribuível sem condição*.

Alternativa segura: versionar o **mart agregado** (24 linhas, sem microdado individual)
em vez do recorte bruto. Resolve a demonstração sem a dúvida jurídica.

## Quando abrir

| | |
|---|---|
| **A. Agora** | ❌ O repo hoje afirma coisas falsas ([F02](../fatias/F02-concluir-migracao-duckdb.md), [F03](../fatias/F03-agendamento-real.md)) e não sobe num clone limpo ([F01](../fatias/F01-destravar-o-clone.md)). Primeira impressão é uma só. |
| **B. Depois de F01+F02+F05** ✅ | Sobe num clone limpo, documentação bate com o código, o número publicado está certo. Mínimo defensável. |
| **C. Depois de F10+F14** ✅✅ | Com resultado visível e narrativa. É quando o repo passa a *vender*. |

## Recomendação

**B como piso, C como alvo.** Não abra antes de B — um repositório que contradiz a si
mesmo custa mais que um repositório privado.

Um detalhe de calendário: abrir em B e ir commitando as fatias seguintes **em público**
tem valor próprio — mostra evolução e cadência, que é justamente o que o commit único
de hoje não mostra ([F14](../fatias/F14-narrativa-do-repositorio.md)).

## Decisão

> **Data:** 21/09/2026
> **Escolha:** abrir depois de **F01 + F02 + F05** (opção B como piso) e evoluir em
> público até F10 + F14 (opção C como alvo).
> **Porquê:** é o mínimo defensável (sobe num clone limpo, docs batem com o código, o
> número de salário está certo), e os commits seguintes em público mostram cadência.

**O que muda:** o repositório continua **privado** até as três fatias acima. O arquivo de
boletins da [F15](../fatias/F15-entrega-por-email-e-arquivo.md) é um repositório privado
**separado**, então abrir este não o expõe.

**Ainda em aberto dentro desta decisão:** versionar uma amostra do recorte ou só o mart
agregado ([F10](../fatias/F10-camada-analitica.md)). Antes, confirmar os termos de uso do
PDET para redistribuição. A lista de destinatários do boletim é dado pessoal (LGPD) e
nunca entra no repositório.
