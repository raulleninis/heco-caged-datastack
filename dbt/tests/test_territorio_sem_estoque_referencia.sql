{{ config(severity='warn') }}

-- Avisa se um território ATIVO (seeds/territorios.csv) não tem estoque de referência (F20):
-- arquivo ainda não carregado (gov.br indisponível na primeira carga) ou código que não aparece
-- no arquivo do MTE. Nada quebra: ele mantém o fluxo, e estoque e taxa ficam NULL.

select t.territorio, t.nome
from {{ ref('territorios') }} t
where t.ativo
  and t.territorio not in (
      select distinct territorio from {{ ref('mart_estoque') }} where competencia_referencia is not null
  )
