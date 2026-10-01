-- Falha se o marco zero de algum território estiver incompleto ou ambíguo (F16): exatamente
-- os seis grupamentos, uma linha cada, uma só data de referência e um só corte de
-- retificações. Um grupamento faltando daria estoque NULL nele; uma data dupla, estoque
-- somado de dois marcos.

select
    territorio,
    count(*)                                  as linhas,
    count(distinct grupamento)                as grupamentos,
    count(distinct data_referencia)           as datas_referencia,
    count(distinct retificacoes_ate)          as cortes_retificacao
from {{ ref('stg_marco_zero_estoque') }}
group by territorio
having count(*) != 6
    or count(distinct grupamento) != 6
    or count(distinct data_referencia) != 1
    or count(distinct retificacoes_ate) != 1
