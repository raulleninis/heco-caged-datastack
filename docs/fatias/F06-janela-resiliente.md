# F06 · Janela resiliente de competências

| | |
|---|---|
| **Esforço** | M (meio dia) |
| **Fase** | pré-produção |
| **Depende de** | [F04](F04-religar-dbt-no-flow.md) |
| **Resolve** | Achado E ([evidência E7](../revisao/03-evidencias.md#e7-defasagem-de-2-competências--bug-de-janela)) |

## Problema

`competencia_alvo()` devolve **sempre e apenas o mês anterior**:

```python
def competencia_alvo() -> str:
    hoje = date.today()
    ano, mes = hoje.year, hoje.month - 1
    ...
```
— [ingest_caged.py:22-28](../../pipeline/flows/ingest_caged.py#L22-L28)

O flow diário pergunta por essa competência, e só por ela. Se ela não estiver no FTP,
encerra sem erro e tenta de novo amanhã — **com a mesma competência, até virar o mês**.
Quando o mês vira, o alvo muda e a competência anterior **nunca mais é solicitada**.

### Isso já aconteceu

| | |
|---|---|
| Publicado no FTP | 202601 … **202607** |
| Ingerido pelo projeto | 202601 … **202605** |
| Alvo de hoje (21/09/2026) | **202608** — ainda não publicado |

**202606 e 202607 estão disponíveis e são inalcançáveis pelo flow diário.**
Em outubro o alvo vira 202609, e a lacuna só cresce.

### A causa de fundo é uma premissa errada

O `CLAUDE.MD` afirma defasagem de *"1 mês"*. A defasagem **real observada** é de
**1,5 a 2 meses** — hoje é 21 de setembro e a competência de agosto não saiu.
Uma janela de exatamente 1 mês é estruturalmente incompatível com essa fonte.

## Escopo

1. Trocar "qual é o mês anterior?" por **"o que está no FTP que eu ainda não tenho?"**.
   O flow passa a varrer as competências dos últimos *N* meses (sugestão: 6) e
   processar toda lacuna encontrada.
2. Manter um registro do que já foi ingerido, para não rebaixar tudo todo dia.
   Um controle por presença de arquivo já resolve; uma tabela de controle no warehouse
   é mais explícita e rastreável.
3. Reprocessar competências recentes mesmo que já ingeridas — o PDET **revisa**
   competências publicadas. Ver [F12](F12-for-exc-reconciliacao.md).
4. Corrigir a afirmação de defasagem no `CLAUDE.MD`.

## Ganho colateral

Com varredura de lacunas, `ingest_caged` e `backfill_caged` convergem quase para a
mesma função — `backfill` vira "varra o ano inteiro" e o diário vira "varra os
últimos 6 meses". Isso **elimina a duplicação** de lógica que hoje existe entre os
dois flows (e o buraco do `backfill` que nunca chama o dbt).

## Critério de aceite

```bash
# com dados até 202605 em disco e FTP até 202607:
# um run do flow diário deve ingerir 202606 E 202607
```

E o teste de regressão que importa: **remova** `CAGEDMOV202603.txt` de
`data/raw/extraido/`, rode o flow, e confirme que ele **rebaixa a competência que falta** —
não só a mais recente.
