{{ config(
    materialized='table'
) }}

select
    competencia_mov,
    grupamento,
    count(*) filter (where saldo_movimentacao = 1) as admissoes,
    count(*) filter (where saldo_movimentacao = -1) as desligamentos,
    sum(saldo_movimentacao) as saldo_liquido,
    count(*) filter (where saldo_movimentacao = 1 and unidade_salario_codigo = 5 and valor_salario_fixo > 0) as admissoes_com_salario_valido,
    round(
        percentile_disc(0.5) within group (order by valor_salario_fixo)
        filter (where saldo_movimentacao = 1 and unidade_salario_codigo = 5 and valor_salario_fixo > 0),
        2
    ) as salario_mediano_admissao,
    round(
        avg(valor_salario_fixo)
        filter (where saldo_movimentacao = 1 and unidade_salario_codigo = 5 and valor_salario_fixo > 0),
        2
    ) as salario_medio_admissao
from {{ ref('stg_caged_movimentacoes') }}
group by 1, 2
order by 1, 2
