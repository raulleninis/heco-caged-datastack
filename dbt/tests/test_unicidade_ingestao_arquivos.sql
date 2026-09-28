-- Falha se um arquivo (tipo, competência) aparecer mais de uma vez no registro de ingestão
-- (F16). Reprocessar substitui o registro; duas linhas indicariam carga somada por cima.

select tipo, competencia_arquivo, count(*) as registros
from {{ source('warehouse', 'ingestao_arquivos') }}
group by 1, 2
having count(*) > 1
