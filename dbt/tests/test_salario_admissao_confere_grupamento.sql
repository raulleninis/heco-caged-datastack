-- F19: para o município do boletim, a base do salário por território (admissões com
-- salário válido) é a soma da base por grupamento do mart_caged_mensal_grupamento (D05).
with por_grupamento as (
    select competencia_mov, sum(admissoes_com_salario_valido) as n
    from {{ ref('mart_caged_mensal_grupamento') }}
    group by 1
)
select g.competencia_mov, g.n, s.admissoes_com_salario_valido
from por_grupamento g
full join (
    select * from {{ ref('mart_salario_admissao') }}
    where territorio = cast({{ var('municipio_boletim') }} as varchar)
) s using (competencia_mov)
where coalesce(g.n, 0) != coalesce(s.admissoes_com_salario_valido, 0)
