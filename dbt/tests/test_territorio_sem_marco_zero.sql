{{ config(severity='warn') }}

-- Avisa se um território ATIVO (seeds/territorios.csv) não tem marco zero (F16). Nada
-- quebra: ele mantém o fluxo, e estoque e taxa ficam NULL no mart_estoque.

select t.territorio, t.nome
from {{ ref('territorios') }} t
where t.ativo
  and t.territorio not in (select territorio from {{ ref('stg_marco_zero_estoque') }})
