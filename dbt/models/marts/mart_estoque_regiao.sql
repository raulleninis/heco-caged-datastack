{#
    Estoque e taxa de uma REGIÃO (seeds/regioes.csv) como soma dos seus municípios no
    mart_estoque, cada um com o próprio marco zero (F19 parte 1; roteiro, seção 1.3).

    O estoque da região só existe quando TODOS os membros têm estoque naquela competência:
    um membro sem marco zero daria um estoque parcial com cara de completo. Membro inativo
    é erro de configuração (test_regiao_membros_ativos). Nunca soma UF com municípios: a
    região só aceita territórios do tipo município.
#}

with membros as (
    select r.regiao, r.nome, r.territorio
    from {{ ref('regioes') }} r
),

n_membros as (
    select regiao, count(*) as membros from membros group by 1
),

agregado as (
    select
        m.regiao,
        m.nome,
        e.grupamento,
        e.competencia_mov,
        sum(e.saldo_consolidado)          as saldo_consolidado,
        sum(e.estoque)                    as estoque_soma,
        count(e.estoque)                  as membros_com_estoque,
        count(*)                          as membros_presentes
    from membros m
    join {{ ref('mart_estoque') }} e on e.territorio = m.territorio
    group by 1, 2, 3, 4
),

serie as (
    select
        a.regiao,
        a.nome,
        a.grupamento,
        a.competencia_mov,
        a.saldo_consolidado,
        case when a.membros_com_estoque = n.membros then a.estoque_soma end as estoque
    from agregado a
    join n_membros n using (regiao)
)

select
    regiao,
    nome,
    grupamento,
    competencia_mov,
    saldo_consolidado,
    estoque,
    saldo_consolidado / nullif(
        lag(estoque) over (partition by regiao, grupamento order by competencia_mov), 0
    ) as taxa_variacao_mensal
from serie
order by 1, 3, 4
