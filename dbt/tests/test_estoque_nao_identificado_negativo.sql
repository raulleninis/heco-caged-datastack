{{ config(severity='warn') }}

-- Avisa quando o estoque de "Não Identificado" (seção CNAE Z) fica negativo (F16). É warn, não
-- error: em Sergipe (UF) a série é negativa no próprio painel do MTE (marco zero da UF = 5,
-- menor que o de Aracaju = 16), e o mart reproduz o painel em 84 de 84 valores. Esperado hoje:
-- Sergipe (28). Um território novo aparecendo aqui merece ser conferido com o painel.
-- Ver marco-zero/FONTE.md e D11.

select territorio, grupamento, competencia_mov, estoque
from {{ ref('mart_estoque') }}
where estoque < 0
  and grupamento = 'Não Identificado'
