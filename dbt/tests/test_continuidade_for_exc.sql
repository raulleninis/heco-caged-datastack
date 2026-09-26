{{ config(severity='warn') }}

-- Avisa se faltar o registro de ingestão de algum CAGEDFOR/CAGEDEXC. WARN e não erro: o PDET
-- pode publicar o FOR/EXC de uma competência depois do MOV, e isso não deve derrubar o run.
-- Enquanto faltar arquivo, o saldo consolidado daquela declaração está incompleto.
--
-- Exceções verificadas no FTP (26/09/2026): o PDET não publicou FOR de 202001 nem EXC de
-- 202001 a 202003 (o sistema novo começou em jan/2020).

with ultima as (
    select max(competencia_mov) as u from {{ ref('stg_caged_movimentacoes') }}
),

esperado as (
    select 'FOR' as tipo, cast(strftime(d, '%Y%m') as bigint) as competencia
    from generate_series(date '2020-02-01', (select make_date(u // 100, cast(u % 100 as integer), 1) from ultima), interval 1 month) as t(d)
    union all
    select 'EXC', cast(strftime(d, '%Y%m') as bigint)
    from generate_series(date '2020-04-01', (select make_date(u // 100, cast(u % 100 as integer), 1) from ultima), interval 1 month) as t(d)
)

select e.tipo, e.competencia as competencia_sem_registro
from esperado e
left join {{ source('warehouse', 'ingestao_arquivos') }} i
    on i.tipo = e.tipo and i.competencia_arquivo = e.competencia
where i.tipo is null
