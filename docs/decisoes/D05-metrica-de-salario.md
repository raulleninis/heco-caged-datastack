# D05 · Qual métrica de salário publicar

**Status:** decidida (21/09/2026) · **Bloqueia:** [F05](../fatias/F05-corrigir-salario-medio.md) · **Urgência:** alta

## Contexto

`salario_medio_admissao` está errado hoje — não por imprecisão, mas por erro de
cálculo. Um registro com **unidade de salário = hora** e valor de R$ 356.620,00 inflou
a média de Construção/202603 em **268%**
([evidência E6](../revisao/03-evidencias.md#e6-salario_medio_admissao-está-errado--mistura-unidades-de-salário)).

Consertar exige decidir **o que a métrica significa**, não só filtrar o outlier.

## Sub-decisões

### 1. Quais unidades de salário entram?

O CAGED traz `unidade_salario_codigo` (hora, dia, semana, quinzena, mês, tarefa).
Somar hora com mês não tem significado.

| opção | efeito |
|---|---|
| **Só mensal (`= 5`)** ✅ | Simples, honesto, é a maioria esmagadora dos registros. Custa perder alguns contratos. |
| Normalizar tudo para base mensal | Mais completo, mas exige premissa sobre jornada (`horas_contratuais` está na staging) — e premissa errada polui pior que exclusão |
| Publicar segmentado por unidade | Mais fiel, mais difícil de ler |

### 2. Média ou mediana?

| | |
|---|---|
| **Média** | O que está lá hoje. Sensível a outlier — já se provou frágil nesta base. |
| **Mediana** ✅ | Robusta. Para salário, é a estatística padrão em estudos de mercado de trabalho (o próprio IBGE/PDET usa). |
| **Ambas** ✅✅ | Publicar as duas lado a lado. A divergência entre elas **é informação** — mostra concentração. |

### 3. O que fazer com `salario = 0`?

O CAGED é declaratório; zero costuma significar "não informado", não "trabalha de graça".
Incluir puxa a média para baixo de forma silenciosa.

**Recomendação:** excluir do cálculo e publicar `admissoes_com_salario_valido` ao lado,
para que o leitor saiba a base.

### 4. E o outlier legítimo?

Um salário de R$ 356.620/hora é claramente erro de digitação na fonte. Mas
R$ 25.000/mês pode ser real.

| opção | |
|---|---|
| **Não truncar; usar mediana** ✅ | A mediana já é imune. Não inventa regra arbitrária. |
| Winsorizar (cortar percentis extremos) | Estatisticamente defensável, mas precisa ser documentado ou vira número inexplicável |
| Limite fixo | Simples, arbitrário, envelhece mal com inflação |

## Recomendação consolidada

```
- filtrar unidade_salario_codigo = 5 (mensal)
- excluir salario = 0 e nulos
- publicar mediana E média, lado a lado
- publicar admissoes_com_salario_valido (a base do cálculo)
- NÃO truncar outliers — documentar que a mediana é a métrica de referência
- teste dbt de faixa como rede de segurança (F09)
```

O ganho de portfólio é real: *"publico mediana porque a média é sensível a erro de
digitação na fonte declaratória, e aqui está o caso concreto que me fez mudar"* é uma
resposta de entrevista muito melhor que um `avg()`.

## Decisão

> **Data:** 21/09/2026
> **Escolha:** a recomendação consolidada acima, sem alterações.
> **Porquê:** o número atual está errado por erro de cálculo (E6), não por imprecisão; a
> mediana é imune a erro de digitação na fonte declaratória, sem inventar regra de corte.

### Registro para revisão manual: o que muda

**Nada foi aplicado ao código.** A implementação é a [F05](../fatias/F05-corrigir-salario-medio.md).
Estado anterior = o que o código faz hoje em
[mart_caged_mensal_grupamento.sql:13](../../dbt/models/marts/mart_caged_mensal_grupamento.sql#L13):
`round(avg(salario) filter (where saldo_movimentacao = 1), 2) as salario_medio_admissao`.

| # | Aspecto | Estado anterior | Novo estado | Motivo |
|---|---|---|---|---|
| 1 | Unidades de salário | `avg` sobre **todas** as unidades (hora, dia, semana, quinzena, mês, tarefa), sem filtro | só `unidade_salario_codigo = 5` (mensal) | somar hora com mês não tem significado; 1 registro em hora (R$ 356.620,00) inflou Construção/202603 em 268% |
| 2 | Estatística | só média (`salario_medio_admissao`) | **mediana** (métrica de referência) **e** média, lado a lado | a mediana é robusta a outlier; a divergência entre as duas mostra concentração |
| 3 | `salario = 0` e nulo | zero **entra** e puxa a média para baixo; nulo é ignorado pelo `avg` do SQL | ambos **excluídos** do cálculo | no CAGED, zero costuma significar "não informado" |
| 4 | Base do cálculo | não exposta | nova coluna `admissoes_com_salario_valido` | o leitor precisa saber sobre quantos registros a métrica foi calculada |
| 5 | Outliers | sem defesa | **não truncar**; documentar que a mediana é a referência; teste dbt de faixa como rede de segurança ([F09](../fatias/F09-testes-de-qualidade.md)) | a mediana já é imune; truncar exigiria regra arbitrária que envelhece com a inflação |
| 6 | Grupo sem base válida | `NULL` (ex.: Agropecuária/202603, 0 admissões) | `NULL` explícito continua, e o número de grupos assim **tende a aumentar** | `NULL` é preferível a `0`, que seria lido como salário zero |

**Efeito visível a conferir:** os valores publicados **mudam**. Referência da F05:
Construção/202603 sai de **R$ 7.265,68** para a ordem de **R$ 1.972,43** (média das 66
admissões em unidade mensal; o valor final também depende de excluir `salario = 0`, que
não foi recalculado). O nome da coluna `salario_medio_admissao` passa a significar "média
só de salário mensal válido": decidir na F05 se ela é renomeada para não enganar
consumidores (boletim e planilha da [F15](../fatias/F15-entrega-por-email-e-arquivo.md)).
