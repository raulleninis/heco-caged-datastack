-- Falha se algum estoque for negativo (F16). Um estoque abaixo de zero só sai de marco zero
-- errado, sinal do EXC invertido ou movimentação contada duas vezes.

select territorio, grupamento, competencia_mov, estoque
from {{ ref('mart_estoque') }}
where estoque < 0
