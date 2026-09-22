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

-- DuckDB não permite agregação aninhada (ex.: avg(... max(x) ...)), então
-- os percentis precisam ser resolvidos POR LINHA (via join) antes de entrar
-- em outra agregação — não dá pra chamar max(per.p90) dentro de um avg().
salario_com_percentis as (
    select
        sv.competencia_mov,
        sv.grupamento,
        sv.valor_salario_fixo,
        per.p40,
        per.p90
    from salario_valido sv
    left join percentis per
        on sv.competencia_mov = per.competencia_mov
        and sv.grupamento = per.grupamento
),

metricas_salario as (
    select
        competencia_mov,
        grupamento,
        count(*) as admissoes_com_salario_valido,
        round(avg(valor_salario_fixo), 2) as salario_medio_admissao,
        round(
            avg(case when valor_salario_fixo >= p90 then valor_salario_fixo end) /
            nullif(avg(case when valor_salario_fixo <= p40 then valor_salario_fixo end), 0),
            4
        ) as palma_index_admissao
    from salario_com_percentis
    group by competencia_mov, grupamento
)

select
    c.competencia_mov,
    c.grupamento,
    c.admissoes,
    c.desligamentos,
    c.saldo_liquido,
    coalesce(ms.admissoes_com_salario_valido, 0) as admissoes_com_salario_valido,
    round(per.p50, 2) as salario_mediano_admissao,
    ms.salario_medio_admissao,
    ms.palma_index_admissao
from contagens c
left join metricas_salario ms
    on c.competencia_mov = ms.competencia_mov
    and c.grupamento = ms.grupamento
left join percentis per
    on c.competencia_mov = per.competencia_mov
    and c.grupamento = per.grupamento
order by 1, 2
