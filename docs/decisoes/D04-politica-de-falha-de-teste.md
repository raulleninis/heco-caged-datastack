# D04 · Teste dbt falhando derruba o flow?

**Status:** decidida (21/09/2026) · **Bloqueia:** [F04](../fatias/F04-religar-dbt-no-flow.md) · **Urgência:** baixa

## Contexto

A task `run_dbt` levanta exceção em qualquer `returncode != 0`:

```python
    if result.returncode != 0:
        logger.error(result.stderr)
        raise RuntimeError(f"dbt {' '.join(comando)} falhou")
```
— [ingest_caged.py:107-109](../../pipeline/flows/ingest_caged.py#L107-L109)

Isso está **certo para `dbt run`** — se a transformação falhou, o flow falhou.

Para `dbt test` a pergunta é diferente: um teste de qualidade falhando significa
"o dado chegou estranho", não "o pipeline quebrou". O dado **já está no warehouse**
quando o teste roda.

## Opções

| | |
|---|---|
| **A. Falhar sempre** | Simples e alto. Mas um `accepted_values` estourando por uma unidade de salário nova deixa o flow vermelho sem que nada esteja quebrado. |
| **B. `dbt test` só avisa** | Flow verde, alerta separado. Risco: alerta que não derruba nada vira alerta ignorado. |
| **C. Severidade por teste** ✅ | O dbt já suporta `severity: warn` vs `error` por teste. Testes estruturais (unicidade, `saldo_movimentacao ∈ {1,-1}`) → `error`. Testes de plausibilidade (faixa de salário) → `warn`. |

## Recomendação

**Opção C.** É o recurso que o dbt oferece exatamente para isso, não exige código no
flow, e força a classificar cada teste — o que é um exercício útil por si.

Regra prática: **`error` se o número publicado fica errado; `warn` se o número fica
suspeito.**

> Detalhe a corrigir junto ([F04](../fatias/F04-religar-dbt-no-flow.md)): hoje o erro
> loga `result.stderr`, mas o dbt escreve o diagnóstico no **stdout**. Em falha, logue
> os dois — hoje o log mais útil é descartado.

## Decisão

> **Data:** 21/09/2026
> **Escolha:** **C** — severidade por teste (`error` vs `warn`).
> **Porquê:** é o recurso do dbt para isso, não exige código no flow e força a classificar
> cada teste. Regra: `error` se o número publicado fica errado; `warn` se fica suspeito.

**O que muda** *(a implementar na [F04](../fatias/F04-religar-dbt-no-flow.md))*: hoje
`run_dbt` levanta erro em qualquer `returncode != 0` e loga só o `stderr`. Depois: testes
estruturais reprovados derrubam o flow (e, com a [F15](../fatias/F15-entrega-por-email-e-arquivo.md),
**impedem o envio do boletim**); testes de plausibilidade só avisam; o log de falha inclui
`stdout` e `stderr`.
