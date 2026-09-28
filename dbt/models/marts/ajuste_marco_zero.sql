{{ config(materialized='table') }}

{#
    Ajuste CALCULADO do marco zero (F16 item 4, D11). O valor manual nunca é editado.

    Entra aqui uma linha de FOR/EXC que corrige uma competência ATÉ a do marco zero e que
    veio num arquivo POSTERIOR a `retificacoes_ate` (o que o painel já tinha incorporado
    quando o marco foi coletado). As de arquivos anteriores já estão no número do painel:
    somá-las de novo contaria duas vezes (em Socorro, 300 linhas com efeito −106).

    Vazio em regime normal; test_ajuste_marco_zero_acionado avisa (warn) quando não estiver.
#}

with eventos as (
    {{ efeito_no_saldo() }}
),

marco as (
    select distinct territorio, competencia_marco_zero, retificacoes_ate
    from {{ ref('stg_marco_zero_estoque') }}
)

select
    e.territorio,
    e.grupamento,
    count(*)                      as linhas,
    sum(e.efeito)                 as ajuste,
    min(e.competencia_arquivo)    as primeiro_arquivo,
    max(e.competencia_arquivo)    as ultimo_arquivo
from eventos e
join marco m on e.territorio = m.territorio
where e.tipo in ('FOR', 'EXC')
  and e.competencia_mov <= m.competencia_marco_zero
  and e.competencia_arquivo > m.retificacoes_ate
group by 1, 2
