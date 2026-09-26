-- Falha se o mart reconciliado for incoerente consigo mesmo ou com o mart só-MOV.
--  1. saldo_consolidado = saldo_mov + saldo_fora_prazo + saldo_exclusoes
--  2. saldo_mov bate com mart_caged_mensal_grupamento.saldo_liquido (a parte MOV dos dois
--     marts vem da mesma staging: divergir é bug de modelagem)

with reconciliado as (
    select * from {{ ref('mart_caged_reconciliado') }}
),

so_mov as (
    select competencia_mov, grupamento, saldo_liquido
    from {{ ref('mart_caged_mensal_grupamento') }}
)

select
    r.competencia_mov,
    r.grupamento,
    r.saldo_consolidado,
    r.saldo_mov + r.saldo_fora_prazo + r.saldo_exclusoes as saldo_esperado,
    r.saldo_mov,
    coalesce(m.saldo_liquido, 0) as saldo_do_mart_so_mov
from reconciliado r
left join so_mov m
    on r.competencia_mov = m.competencia_mov
   and r.grupamento = m.grupamento
where r.saldo_consolidado != r.saldo_mov + r.saldo_fora_prazo + r.saldo_exclusoes
   or r.saldo_mov != coalesce(m.saldo_liquido, 0)
