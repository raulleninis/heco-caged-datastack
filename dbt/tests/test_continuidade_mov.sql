-- Falha se faltar o CAGEDMOV de alguma competência entre 202001 (início do Novo CAGED) e a
-- mais recente carregada. Uma lacuna aqui distorce o saldo, e o estoque acumulado (F16).

with esperado as (
    select cast(strftime(d, '%Y%m') as bigint) as competencia
    from generate_series(
        date '2020-01-01',
        (select make_date(max(competencia_mov) // 100, cast(max(competencia_mov) % 100 as integer), 1)
         from {{ ref('stg_caged_movimentacoes') }}),
        interval 1 month
    ) as t(d)
)

select competencia as competencia_sem_mov
from esperado
where competencia not in (select distinct competencia_mov from {{ ref('stg_caged_movimentacoes') }})
