{{ config(
    materialized='table'
) }}

with admissoes_validas as (
    select
        competencia_mov,
        grupamento,
        valor_salario_fixo,
        saldo_movimentacao
    from {{ ref('stg_caged_movimentacoes') }}
    where saldo_movimentacao = 1
      and unidade_salario_codigo = 5
      and valor_salario_fixo > 0
),

percentis as (
    select
        competencia_mov,
        grupamento,
        percentile_disc(0.4) within group (order by valor_salario_fixo) as p40,
        percentile_disc(0.5) within group (order by valor_salario_fixo) as p50,
        percentile_disc(0.9) within group (order by valor_salario_fixo) as p90
    from admissoes_validas
    group by 1, 2
)

select
    av.competencia_mov,
    av.grupamento,
    count(*) filter (where av.saldo_movimentacao = 1) as admissoes,
    count(*) filter (where av.saldo_movimentacao = -1) as desligamentos,
    sum(av.saldo_movimentacao) as saldo_liquido,
    count(*) as admissoes_com_salario_valido,
    round(p50, 2) as salario_mediano_admissao,
    round(avg(av.valor_salario_fixo), 2) as salario_medio_admissao,
    round(
        avg(case when av.valor_salario_fixo >= per.p90 then av.valor_salario_fixo end) /
        nullif(avg(case when av.valor_salario_fixo <= per.p40 then av.valor_salario_fixo end), 0),
        4
    ) as palma_index_admissao
from admissoes_validas av
left join percentis per on av.competencia_mov = per.competencia_mov and av.grupamento = per.grupamento
group by 1, 2, per.p50, per.p40, per.p90
order by 1, 2
