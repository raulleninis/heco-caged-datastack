# D08 · Gestão de segredos na nuvem

**Status:** decidida (21/09/2026) · **Bloqueia:** [F13](../fatias/F13-migracao-nuvem.md) · **Urgência:** baixa

## Contexto

Hoje: tudo em `.env` no disco, injetado como variável de ambiente pelo Compose.
Para um servidor caseiro atrás de Tailscale, **isso é adequado** — não há o que
consertar agora.

Três coisas mudam na nuvem:

1. Variável de ambiente em container é legível por `docker inspect` e costuma
   aparecer em log de plataforma.
2. `.env` em disco de VM sobrevive a snapshot, backup e imagem — e vaza junto.
3. O **CrewAI** ([roadmap](../../README.md)) traz uma chave de API de LLM, que é
   segredo com **custo financeiro direto** — categoria diferente de uma senha de
   Postgres local.

> Se a [D01](D01-duckdb-only-ou-postgres.md) for DuckDB-only, `POSTGRES_USER` e
> `POSTGRES_PASSWORD` somem, e o `.env` fica só com `PREFECT_HOST` — o problema
> quase desaparece sozinho.

## Opções

| | |
|---|---|
| **A. Manter `.env`** | Simples. Aceitável se o único segredo for `PREFECT_HOST`. Insuficiente quando entrar chave de LLM. |
| **B. Segredos da plataforma** ✅ (GitHub Actions Secrets, Prefect Blocks, Secret Manager) | Casa com a [D02](D02-modelo-de-execucao.md); sem segredo em disco; rotação viável |
| **C. Cofre dedicado** (Vault, Doppler) | Correto e exagerado para 1 pessoa e 2 segredos |

## Recomendação

**A até a nuvem; B junto com a [F13](../fatias/F13-migracao-nuvem.md).**

Escolha o mecanismo pela [D02](D02-modelo-de-execucao.md): Actions → Secrets;
Prefect Cloud → Blocks; container gerenciado → Secret Manager do provedor.

Quando o CrewAI entrar, trate a chave de LLM como categoria própria: **limite de gasto
configurado no provedor**, chave dedicada ao projeto, e rotação se o repositório for
público. Chave de LLM vazada não é constrangimento — é fatura.

## Decisão

> **Data:** 21/09/2026
> **Escolha:** **A** — `.env` fora do git, permissão `600`, credenciais de **escopo mínimo**.
> **Porquê:** é adequado para 1 VM e 1 pessoa. B (Blocks do Prefect) só moveria o
> segredo para o banco do Prefect local; C é exagero para poucos segredos.

**O que muda:** com a [D02](D02-modelo-de-execucao.md) = A, a opção B "segredos da
plataforma" perdeu o sentido que tinha para a nuvem. Os segredos previstos passam a ser:

| segredo | escopo mínimo |
|---|---|
| Credencial de e-mail (SMTP/API) | só envio |
| Chave de escrita do repositório do arquivo ([F15](../fatias/F15-entrega-por-email-e-arquivo.md)) | *deploy key* de um único repositório |
| Chave de LLM (quando o CrewAI entrar) | chave dedicada, **limite de gasto no provedor**, rotação se o repositório for público |

Antes: só `PREFECT_HOST` (e `POSTGRES_*` até a [F02](../fatias/F02-concluir-migracao-duckdb.md)).
Revisitar esta decisão se algum dia entrar Prefect Cloud ou execução gerenciada.
