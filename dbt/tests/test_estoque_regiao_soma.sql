-- F19: o estoque da região é a soma exata do estoque dos membros, quando todos têm estoque.
with membros as (
    select r.regiao, e.grupamento, e.competencia_mov,
           sum(e.estoque) as soma, count(e.estoque) as com_estoque, count(*) as n
    from {{ ref('regioes') }} r
    join {{ ref('mart_estoque') }} e using (territorio)
    group by 1, 2, 3
)
select g.regiao, g.grupamento, g.competencia_mov, g.estoque, m.soma
from {{ ref('mart_estoque_regiao') }} g
join membros m using (regiao, grupamento, competencia_mov)
where m.com_estoque = m.n and g.estoque is distinct from m.soma
