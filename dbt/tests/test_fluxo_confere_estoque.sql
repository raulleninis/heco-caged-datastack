-- F19: o saldo do mart_fluxo, somado por território × grupamento × competência, é o
-- saldo_consolidado do mart_estoque (mesma regra, macro efeito_no_saldo). Diferença aqui
-- quer dizer que a desagregação perdeu ou duplicou eventos.
with fluxo as (
    select territorio, grupamento, competencia_mov, sum(saldo) as saldo
    from {{ ref('mart_fluxo') }}
    group by 1, 2, 3
)
select e.territorio, e.grupamento, e.competencia_mov, e.saldo_consolidado, f.saldo
from {{ ref('mart_estoque') }} e
full join fluxo f using (territorio, grupamento, competencia_mov)
where coalesce(e.saldo_consolidado, 0) != coalesce(f.saldo, 0)
