{{ config(severity='warn') }}

-- Avisa se um território com movimentação na staging não tem marco zero (F16). Nada quebra:
-- ele mantém o fluxo, e estoque e taxa ficam NULL no mart_estoque.

select distinct e.territorio
from ({{ efeito_no_saldo() }}) e
where e.tipo = 'MOV'
  and e.territorio not in (select territorio from {{ ref('stg_marco_zero_estoque') }})
