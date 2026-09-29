-- F19: o grão de cada mart novo é único (fluxo, perfil e região).
select 'mart_fluxo' as mart, count(*) as linhas
from {{ ref('mart_fluxo') }}
group by territorio, competencia_mov, grupamento, subgrupamento, divisao_cnae
having count(*) > 1
union all
select 'mart_perfil_movimentacoes', count(*)
from {{ ref('mart_perfil_movimentacoes') }}
group by territorio, competencia_mov, dimensao, categoria
having count(*) > 1
union all
select 'mart_estoque_regiao', count(*)
from {{ ref('mart_estoque_regiao') }}
group by regiao, grupamento, competencia_mov
having count(*) > 1
