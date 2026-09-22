-- Falha se (competencia_mov, grupamento) não for único no mart.
-- dbt_utils não está instalado (sem packages.yml), então este teste
-- singular substitui unique_combination_of_columns.

select
    competencia_mov,
    grupamento,
    count(*) as linhas
from {{ ref('mart_caged_mensal_grupamento') }}
group by competencia_mov, grupamento
having count(*) > 1
