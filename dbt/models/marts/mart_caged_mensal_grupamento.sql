{{ config(
    materialized='table',
    database='postgres_db',
    schema='public'
) }}

select
    competencia_mov,
    grupamento,
    count(*) filter (where saldo_movimentacao = 1)  as admissoes,
    count(*) filter (where saldo_movimentacao = -1) as desligamentos,
    sum(saldo_movimentacao)                          as saldo_liquido,
    round(avg(salario) filter (where saldo_movimentacao = 1), 2) as salario_medio_admissao
from {{ ref('stg_caged_movimentacoes') }}
group by 1, 2
order by 1, 2
