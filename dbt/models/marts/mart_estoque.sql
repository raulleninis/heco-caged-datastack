{{ config(materialized='table') }}

{#
    Estoque de emprego por território × grupamento × competência (F16, D11):

        estoque(t) = marco_zero + ajuste_marco_zero + Σ saldo_consolidado de (marco, t]

    saldo_consolidado = MOV + FOR − EXC por competência de movimentação (macro
    efeito_no_saldo, mesma regra do mart_caged_reconciliado).

    - estoque é NULL antes da competência do marco zero e em território sem marco zero:
      o fluxo continua existindo, o nível não. Na competência do marco, estoque = marco.
    - Os saldos até a competência do marco (hoje jan–mar/2020) aparecem como fluxo, mas NÃO
      entram no estoque: o marco do painel já os contém (e jan/mar divergem do painel, ver
      docs/auditorias/2026-09-28-painel-vs-mart-socorro.md).
    - taxa_variacao_mensal = saldo ÷ estoque do mês anterior (fração, não %); NULL se não
      houver estoque anterior ou se ele for 0.
    - Territórios: os que têm movimentação na staging (hoje só Socorro). Marco zero de
      território sem movimentação é ignorado, para não virar um estoque parado.

    O estoque é uma ESTIMATIVA a partir do marco zero, e muda quando chegam retificadores
    de meses passados (FOR retroage ~12 meses, EXC até 2020).
#}

with eventos as (
    {{ efeito_no_saldo() }}
),

marco as (
    select territorio, grupamento, estoque, competencia_marco_zero
    from {{ ref('stg_marco_zero_estoque') }}
),

ajuste as (
    select territorio, grupamento, ajuste
    from {{ ref('ajuste_marco_zero') }}
),

competencias as (
    select cast(strftime(d, '%Y%m') as bigint) as competencia_mov
    from generate_series(
        date '2020-01-01',
        (select make_date(max(competencia_mov) // 100, cast(max(competencia_mov) % 100 as integer), 1)
         from {{ ref('stg_caged_movimentacoes') }}),
        interval 1 month
    ) as t(d)
),

territorios_ativos as (
    select distinct territorio from eventos where tipo = 'MOV'
),

grupamentos as (
    select distinct territorio, grupamento from eventos
    union
    select m.territorio, m.grupamento
    from marco m
    join territorios_ativos using (territorio)
),

saldo as (
    select territorio, grupamento, competencia_mov, sum(efeito) as saldo_consolidado
    from eventos
    group by 1, 2, 3
),

serie as (
    select
        g.territorio,
        g.grupamento,
        c.competencia_mov,
        coalesce(s.saldo_consolidado, 0)          as saldo_consolidado,
        m.competencia_marco_zero,
        m.estoque + coalesce(a.ajuste, 0)         as marco_zero_ajustado
    from grupamentos g
    cross join competencias c
    left join saldo s
        on s.territorio = g.territorio and s.grupamento = g.grupamento
       and s.competencia_mov = c.competencia_mov
    left join marco m
        on m.territorio = g.territorio and m.grupamento = g.grupamento
    left join ajuste a
        on a.territorio = g.territorio and a.grupamento = g.grupamento
),

com_estoque as (
    select
        *,
        case
            when competencia_marco_zero is null or competencia_mov < competencia_marco_zero then null
            else marco_zero_ajustado + sum(
                    case when competencia_mov > competencia_marco_zero then saldo_consolidado else 0 end
                 ) over (partition by territorio, grupamento order by competencia_mov
                         rows between unbounded preceding and current row)
        end as estoque
    from serie
)

select
    territorio,
    grupamento,
    competencia_mov,
    saldo_consolidado,
    estoque,
    saldo_consolidado / nullif(
        lag(estoque) over (partition by territorio, grupamento order by competencia_mov), 0
    ) as taxa_variacao_mensal,
    competencia_marco_zero
from com_estoque
order by 1, 2, 3
