-- Falha se salario_mediano_admissao ou salario_medio_admissao caírem fora
-- de uma faixa plausível para o mercado formal de N. Sra. do Socorro/SE.
--
-- Este é o teste que teria pego o erro da F05: um único registro com
-- unidade de salário = hora e valor de R$ 356.620,00 inflou a média de
-- Construção/202603 para R$ 7.265,68 (+268% sobre os meses vizinhos,
-- que ficavam em ~R$ 1.900-2.100).
--
-- Limite superior validado contra dados reais (202601-202607): salário
-- médio observado varia ~R$ 1.600-2.500 entre grupamentos. Teto de 6.000
-- dá margem de mais de 2x sobre o maior valor real visto, mas ainda pega
-- o caso de R$ 7.265,68 — um teto de 20.000 (tentativa inicial) NÃO
-- pegava esse valor especificamente, e só foi descoberto reproduzindo o
-- defeito de propósito em dados reais (ver F08b).
--
-- Ajuste os limites se o mercado local mudar de patamar de forma legítima
-- (ex.: reajuste de salário mínimo, novo grande empregador no município).

-- severity=warn (D04): teste de PLAUSIBILIDADE — o número fica suspeito, não
-- errado. Reprova sem derrubar o flow nem bloquear a deleção do .txt, mas o
-- flow alerta (ver _transformar / F11).
{{ config(severity='warn') }}

select
    competencia_mov,
    grupamento,
    salario_mediano_admissao,
    salario_medio_admissao
from {{ ref('mart_caged_mensal_grupamento') }}
where (salario_mediano_admissao is not null and salario_mediano_admissao not between 500 and 6000)
   or (salario_medio_admissao is not null and salario_medio_admissao not between 500 and 6000)
