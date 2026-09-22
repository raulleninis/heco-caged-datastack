# D01 · DuckDB-only ou manter Postgres?

**Status:** decidida (21/09/2026) · **Bloqueia:** [F02](../fatias/F02-concluir-migracao-duckdb.md) · **Urgência:** alta

## Contexto

A migração Postgres → DuckDB está no meio do caminho. O repositório documenta o
destino como se fosse o presente:

- `CLAUDE.MD`: *"Postgres e Metabase foram removidos deliberadamente"*
- `README.md`: `[x] remoção do Postgres e do Metabase`
- `README.md`, linha seguinte: `[ ] Ajustes finais de consolidação da migração`

Estado real: o mart vive em `main_public.mart_caged_mensal_grupamento` **no Postgres**;
o `.duckdb` tem 274 KB e contém só uma view; e o projeto dbt **não faz parse** sem
`POSTGRES_HOST` ([E2](../revisao/03-evidencias.md#e2-o-projeto-dbt-não-faz-parse-sem-postgres)).

**Não decidir também é uma decisão** — e é a pior das três, porque mantém a
contradição visível para quem avaliar o repositório.

## Opções

### A. Concluir a migração — DuckDB-only ✅ recomendada

| | |
|---|---|
| ✅ | Alinha código e documentação (a incoerência acaba) |
| ✅ | Remove 2 serviços, 1 volume, 2 variáveis de segredo, 1 script de init |
| ✅ | Elimina o Adminer exposto na 8080 — metade do risco de rede da [F13](../fatias/F13-migracao-nuvem.md) some de graça |
| ✅ | Arquitetura mais barata na nuvem: sem banco 24/7 |
| ⚠️ | Warehouse vira **um arquivo** — backup e concorrência passam a ser problema seu ([D03](D03-onde-guardar-os-dados.md)) |
| ⚠️ | Um leitor persistente (dashboard) **bloqueia escrita** — o `CLAUDE.MD` já documenta essa restrição corretamente |
| ⚠️ | Prefect precisa migrar para SQLite, com volume nomeado |

### B. Reverter — assumir Postgres

| | |
|---|---|
| ✅ | Concorrência resolvida; múltiplos leitores sem drama |
| ✅ | Destrava dashboard/BI persistente sem contorção |
| ✅ | "Postgres" é palavra que aparece em descrição de vaga |
| ❌ | Contradiz a direção já documentada — exige reescrever CLAUDE.MD e README |
| ❌ | Banco 24/7 na nuvem: a linha mais cara da fatura para 1 mart de 24 linhas |
| ❌ | Mantém Adminer/porta exposta ou exige substituto |

### C. Híbrido — DuckDB processa, Postgres serve

| | |
|---|---|
| ✅ | Cada ferramenta no que faz melhor |
| ❌ | **É exatamente o estado atual** — que é o problema |
| ❌ | Duas tecnologias de armazenamento para um mart de 24 linhas |

## Recomendação

**Opção A.** O argumento decisivo não é técnico, é de coerência: o repositório é
vitrine, e a contradição entre o que ele afirma e o que ele faz é o achado de maior
custo desta revisão.

O volume de dado também não justifica Postgres — o mart tem **24 linhas**. A restrição
de concorrência do DuckDB só morde quando existir consumidor persistente, o que hoje
não existe; e quando existir, [D03](D03-onde-guardar-os-dados.md) já prevê o caminho
(exportar um `.parquet`/`.csv` de leitura, separado do arquivo de escrita).

> Se a Opção B for escolhida, tudo bem — mas então **atualize o CLAUDE.MD e o README
> no mesmo dia**. O problema nunca foi a escolha; foi a divergência.

## Decisão

> *(Opção A)*
>
> **Data:** 21/09/2026
> **Escolha:** DuckDB-only
> **Porquê:** O volume de dados e o objetivo não justificam a utilização do postgres.
