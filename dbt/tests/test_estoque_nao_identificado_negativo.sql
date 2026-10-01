{{ config(severity='warn') }}

-- Avisa quando o estoque de "Não Identificado" (seção CNAE Z) fica negativo (F16/F20). É warn,
-- não error: em Sergipe (UF) a série é negativa no próprio painel do MTE. O estoque de
-- referência não traz esse grupamento (vale 0 em dez/2025) e os saldos de 2026 o levam a −3
-- em 202608, igual ao painel. Esperado hoje: Sergipe (28). Um território novo aparecendo aqui
-- merece ser conferido com o painel. Ver docs/fatias/F20.

select territorio, grupamento, competencia_mov, estoque
from {{ ref('mart_estoque') }}
where estoque < 0
  and grupamento = 'Não Identificado'
