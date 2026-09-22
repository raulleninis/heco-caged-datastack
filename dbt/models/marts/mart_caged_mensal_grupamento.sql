{{ config(
    materialized='table'
) }}

with base as (
    select
        competencia_mov,
        grupamento,
        saldo_movimentacao,
        unidade_salario_codigo,
        valor_salario_fixo
    from {{ ref('stg_caged_movimentacoes') }}
),

contagens as (
    select
        competencia_mov,
        grupamento,
        count(*) filter (where saldo_movimentacao = 1)  as admissoes,
        count(*) filter (where saldo_movimentacao = -1) as desligamentos,
        sum(saldo_movimentacao)                          as saldo_liquido
    from base
    group by 1, 2
),

salario_valido as (
    select
        competencia_mov,
        grupamento,
        valor_salario_fixo
    from base
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
    from salario_valido
    group by 1, 2
),

metricas_salario as (
    select
        sv.competencia_mov,
        sv.grupamento,
        count(*) as admissoes_com_salario_valido,
        round(max(per.p50), 2) as salario_mediano_admissao,
        round(avg(sv.valor_salario_fixo), 2) as salario_medio_admissao,
        round(
            avg(case when sv.valor_salario_fixo >= max(per.p90) then sv.valor_salario_fixo end) /
            nullif(avg(case when sv.valor_salario_fixo <= max(per.p40) then sv.valor_salario_fixo end), 0),
            4
        ) as palma_index_admissao
    from salario_valido sv
    left join percentis per
        on sv.competencia_mov = per.competencia_mov
        and sv.grupamento = per.grupamento
    group by sv.competencia_mov, sv.grupamento
)

select
    c.competencia_mov,
    c.grupamento,
    c.admissoes,
    c.desligamentos,
    c.saldo_liquido,
    coalesce(ms.admissoes_com_salario_valido, 0) as admissoes_com_salario_valido,
    ms.salario_mediano_admissao,
    ms.salario_medio_admissao,
    ms.palma_index_admissao
from contagens c
left join metricas_salario ms
    on c.competencia_mov = ms.competencia_mov
    and c.grupamento = ms.grupamento
order by 1, 2
