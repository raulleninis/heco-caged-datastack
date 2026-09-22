-- Falha se salario_mediano_admissao ou salario_medio_admissao caírem fora
-- de uma faixa plausível para o mercado formal de N. Sra. do Socorro/SE.
--
-- Este é o teste que teria pego o erro da F05: um único registro com
-- unidade de salário = hora e valor de R$ 356.620,00 inflou a média de
-- Construção/202603 para R$ 7.265,68 (+268% sobre os meses vizinhos,
-- que ficavam em ~R$ 1.900-2.100). Limites abaixo dão margem generosa
-- acima/abaixo do observado, mas continuam capturando outliers grosseiros
-- de digitação na fonte declaratória.
--
-- Ajuste os limites se o mercado local mudar de patamar de forma legítima
-- (ex.: reajuste de salário mínimo, novo grande empregador no município).

select
    competencia_mov,
    grupamento,
    salario_mediano_admissao,
    salario_medio_admissao
from {{ ref('mart_caged_mensal_grupamento') }}
where (salario_mediano_admissao is not null and salario_mediano_admissao not between 500 and 20000)
   or (salario_medio_admissao is not null and salario_medio_admissao not between 500 and 20000)
