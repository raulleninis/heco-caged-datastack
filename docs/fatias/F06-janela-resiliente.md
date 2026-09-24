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

### A causa de fundo é uma janela fixa incompatível com variação

O `CLAUDE.MD` afirma corretamente defasagem de **~1 mês** — a competência é publicada
tipicamente 28-31 dias após seu fechamento. O problema **não é a defasagem em si**,
mas que `competencia_alvo()` assume uma janela rígida ("mês anterior") que não tolera
variação de *quando* o FTP publica.

Se a competência for publicada um dia além da data esperada (antes do mês virar),
a competência fica inacessível ao flow diário até o mês seguinte — e quando chega,
já foi "perdida" por ter sido pulada.

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

E o teste de regressão que importa: remova a competência 202603 da staging
(`delete from stg_caged_movimentacoes where competencia_mov = 202603`), rode o flow, e
confirme que ele **rebaixa a competência que falta** — não só a mais recente.
(Originalmente o critério era remover o `.txt`; desde a F07 fase 2 o `.txt` é deletado
de propósito e a detecção consulta o warehouse.)
