-- Falha se algum estoque for negativo (F16/F20). Um estoque abaixo de zero só sai de referência
-- errada, sinal do EXC invertido ou movimentação contada duas vezes.
--
-- "Não Identificado" fica de fora e tem teste próprio, em warn
-- (test_estoque_nao_identificado_negativo): em Sergipe (UF) esse grupamento é negativo no
-- próprio painel do MTE (−3 em 202608), e o mart o reproduz exatamente.

select territorio, grupamento, competencia_mov, estoque
from {{ ref('mart_estoque') }}
where estoque < 0
  and grupamento != 'Não Identificado'
