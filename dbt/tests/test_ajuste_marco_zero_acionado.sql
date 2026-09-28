{{ config(severity='warn') }}

-- Avisa quando chega um FOR/EXC que corrige competência até a do marco zero, publicado
-- depois da coleta do marco (F16). Não é erro: o ajuste é aplicado automaticamente. É o
-- sinal de que o estoque passou a divergir do marco como foi coletado, e de que vale
-- conferir de novo com o painel.

select territorio, grupamento, linhas, ajuste, primeiro_arquivo, ultimo_arquivo
from {{ ref('ajuste_marco_zero') }}
