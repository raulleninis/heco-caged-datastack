# F05 · Corrigir `salario_medio_admissao`

| | |
|---|---|
| **Esforço** | S (menos de 1 h) |
| **Fase** | agora |
| **Depende de** | [F02](F02-concluir-migracao-duckdb.md) |
| **Resolve** | Achado D ([evidência E6](../revisao/03-evidencias.md#e6-salario_medio_admissao-está-errado--mistura-unidades-de-salário)) |
| **Decisão associada** | [D05 — Qual métrica de salário publicar](../decisoes/D05-metrica-de-salario.md) |

## Problema

**A métrica principal do mart está errada.** Não é imprecisão — é erro de cálculo.

No mart de hoje, 202603 / Construção mostra **R$ 7.265,68**, contra ~R$ 1.900 em todos
os outros meses do mesmo grupamento. A causa:

| unidade de salário | registros | média |
|---|---|---|
| `1` (hora) | **1** | 356.620,00 |
| `5` (mês) | 66 | 1.972,43 |

```
(66 × 1.972,43 + 356.620) ÷ 67 = 7.265,67   ← bate exatamente com o mart
```

Um único registro — com unidade de salário **hora** e valor absurdo vindo da fonte —
inflou em **268%** a métrica de um grupamento inteiro.

São duas falhas somadas:

1. `avg(salario)` mistura unidades heterogêneas. Somar salário/hora com salário/mês
   não tem significado.
2. Não há nenhuma defesa contra outlier da fonte. O CAGED é declaratório: erro de
   digitação do empregador entra no microdado.

## Por que isso importa mais que os outros achados

As outras fatias consertam coisas que **não funcionam**. Esta conserta uma coisa que
**funciona e mente**. Um número errado publicado com confiança é pior que um pipeline
parado — e num projeto de vitrine, é exatamente o tipo de erro que um entrevistador
de vaga de dados procura.

## Escopo

1. Restringir a média à unidade de salário mensal (`unidade_salario_codigo = 5`),
   ou normalizar as demais para base mensal. **Decida em [D05](../decisoes/D05-metrica-de-salario.md).**
2. Excluir `salario = 0` e nulos do cálculo (hoje entram e puxam a média para baixo).
3. Publicar também a **mediana**, que é robusta a outlier — e, para salário,
   geralmente é a estatística mais honesta.
4. Expor `admissoes_com_salario_valido` ao lado da métrica, para que o leitor saiba
   sobre quantos registros a média foi calculada.
5. Adicionar teste dbt que trave regressão — ver [F09](F09-testes-de-qualidade.md).

## Cuidado com `avg` sobre conjunto vazio

Hoje, 202603 / Agropecuária tem **0 admissões** e `salario_medio_admissao` vem `NULL`.
Isso está *tecnicamente* correto, mas depois de filtrar por unidade e por salário > 0,
o número de grupos com média nula vai **aumentar**. Defina como o mart representa
"não há base para calcular" — `NULL` explícito é preferível a `0`, que seria lido
como "salário zero".

## Critério de aceite

```sql
-- nenhum grupamento com média fora de uma faixa plausível
select * from mart_caged_mensal_grupamento
where salario_medio_admissao > 20000;
-- -> 0 linhas

-- 202603/Construção volta a um valor coerente com os meses vizinhos
select competencia_mov, grupamento, salario_medio_admissao, salario_mediano_admissao
from mart_caged_mensal_grupamento
where grupamento = 'Construção' order by 1;
-- -> 202603 na mesma ordem de grandeza de 202602 e 202604 (~1.900-2.100)
```

E os campos de contagem (`admissoes`, `desligamentos`, `saldo_liquido`)
**não podem mudar** — esta fatia só toca em salário.
