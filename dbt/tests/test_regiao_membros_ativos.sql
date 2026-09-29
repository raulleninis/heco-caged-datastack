-- F19: todo membro de uma região é um MUNICÍPIO ATIVO em territorios.csv. Membro inativo
-- deixaria a região sem estoque; uma UF como membro somaria o estado com seus municípios.
select r.regiao, r.territorio, t.tipo, t.ativo
from {{ ref('regioes') }} r
left join {{ ref('territorios') }} t using (territorio)
where t.territorio is null or not t.ativo or t.tipo != 'municipio'
