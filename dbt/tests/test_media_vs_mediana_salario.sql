-- Falha se a média salarial de admissão divergir demais da mediana num
-- grupo com amostra razoável. Outlier puxa a média e não a mediana, então
-- a razão média/mediana denuncia distorção mesmo quando a média absoluta
-- ainda cabe em test_faixa_salario_plausivel.
--
-- Razão real observada (202601-202605, grupos com >= 30 admissões válidas):
-- máximo 1,40. Limite de 1,75 dá margem sobre isso. É uma segunda rede,
-- mais grossa: um R$ 60.000 isolado em grupo de ~67 admissões NÃO chega
-- a 1,75 (quem pega esse caso é test_salario_individual_plausivel); já um
-- R$ 356.620 isolado (defeito da F05) estoura os dois. Grupos com menos de
-- 30 ficam de fora: amostra pequena tem razão naturalmente volátil.

select
    competencia_mov,
    grupamento,
    admissoes_com_salario_valido,
    salario_medio_admissao,
    salario_mediano_admissao,
    round(salario_medio_admissao / salario_mediano_admissao, 2) as razao
from {{ ref('mart_caged_mensal_grupamento') }}
where admissoes_com_salario_valido >= 30
  and salario_mediano_admissao > 0
  and salario_medio_admissao / salario_mediano_admissao > 1.75
