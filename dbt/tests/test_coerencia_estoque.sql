-- Falha se o mart de estoque for incoerente consigo mesmo ou com o reconciliado (F16):
--  1. saldo_consolidado bate com mart_caged_reconciliado (mesma regra MOV + FOR − EXC), no
--     município do boletim, o único que o reconciliado cobre
--  2. depois do marco zero, estoque(t) − estoque(t−1) = saldo_consolidado(t)

with estoque as (
    select
        *,
        lag(estoque) over (partition by territorio, grupamento order by competencia_mov) as estoque_anterior
    from {{ ref('mart_estoque') }}
),

reconciliado as (
    select competencia_mov, grupamento, saldo_consolidado
    from {{ ref('mart_caged_reconciliado') }}
)

select
    e.territorio,
    e.grupamento,
    e.competencia_mov,
    e.saldo_consolidado,
    coalesce(r.saldo_consolidado, 0) as saldo_reconciliado,
    e.estoque,
    e.estoque_anterior
from estoque e
left join reconciliado r
    on r.competencia_mov = e.competencia_mov and r.grupamento = e.grupamento
where (e.territorio = '{{ var('municipio_boletim') }}'
       and e.saldo_consolidado != coalesce(r.saldo_consolidado, 0))
   or (e.competencia_mov > e.competencia_marco_zero
       and e.estoque != e.estoque_anterior + e.saldo_consolidado)
