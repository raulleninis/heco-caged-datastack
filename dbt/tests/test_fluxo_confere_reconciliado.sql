-- F19: para o município do boletim, admissões e desligamentos do mart_fluxo (somados por
-- competência × grupamento) são os consolidados do mart_caged_reconciliado, que foi
-- conferido com o painel do MTE (docs/auditorias/).
with fluxo as (
    select competencia_mov, grupamento,
           sum(admissoes) as admissoes, sum(desligamentos) as desligamentos
    from {{ ref('mart_fluxo') }}
    where territorio = cast({{ var('municipio_boletim') }} as varchar)
    group by 1, 2
)
select r.competencia_mov, r.grupamento,
       r.admissoes_consolidadas, f.admissoes, r.desligamentos_consolidados, f.desligamentos
from {{ ref('mart_caged_reconciliado') }} r
full join fluxo f using (competencia_mov, grupamento)
where coalesce(r.admissoes_consolidadas, 0) != coalesce(f.admissoes, 0)
   or coalesce(r.desligamentos_consolidados, 0) != coalesce(f.desligamentos, 0)
