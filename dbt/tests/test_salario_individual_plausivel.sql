-- Falha se alguma admissão com salário mensal (unidade 5) tiver valor
-- individual acima do teto abaixo.
--
-- Complementa test_faixa_salario_plausivel: aquele olha a média/mediana do
-- mart, e um único outlier moderado (ex.: R$ 60.000 num grupo de ~67
-- admissões) move a média só até ~R$ 2.900, sem estourar o teto de 6.000.
-- Este teste olha o registro na origem, então pega o outlier isolado
-- independentemente do tamanho do grupo (o defeito histórico da F05 foi
-- exatamente um único registro de R$ 356.620,00).
--
-- Teto validado contra dados reais (202601-202605, 4.851 admissões
-- mensais): maior salário legítimo observado = R$ 28.000. Teto de 50.000
-- dá ~1,8x de margem. Ajuste se o mercado local mudar de patamar.

select
    competencia_mov,
    grupamento,
    valor_salario_fixo
from {{ ref('stg_caged_movimentacoes') }}
where saldo_movimentacao = 1
  and unidade_salario_codigo = 5
  and valor_salario_fixo > 50000
