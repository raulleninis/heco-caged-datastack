-- Falha se (territorio, grupamento, competencia_mov) não for único no mart de estoque.

select territorio, grupamento, competencia_mov, count(*) as linhas
from {{ ref('mart_estoque') }}
group by 1, 2, 3
having count(*) > 1
