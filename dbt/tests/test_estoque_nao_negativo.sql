-- Falha se algum estoque for negativo (F16). Um estoque abaixo de zero só sai de marco zero
-- errado, sinal do EXC invertido ou movimentação contada duas vezes.
--
-- "Não Identificado" fica de fora e tem teste próprio, em warn
-- (test_estoque_nao_identificado_negativo): em Sergipe (UF) esse grupamento é negativo no
-- próprio painel do MTE (−4 em 202212, −3 em 202607), e o mart o reproduz exatamente.

select territorio, grupamento, competencia_mov, estoque
from {{ ref('mart_estoque') }}
where estoque < 0
  and grupamento != 'Não Identificado'
