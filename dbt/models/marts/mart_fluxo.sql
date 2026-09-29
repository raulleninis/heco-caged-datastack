{#
    Fluxo RECONCILIADO (MOV + FOR − EXC) por território × competência × grupamento ×
    subgrupamento × divisão CNAE (F19 parte 1). É a base setorial do boletim com IA: o
    grupamento é o nível principal, e subgrupamento e divisão servem à desagregação "só
    quando relevante" (docs/boletim-ia/roteiro.md, seção 1.2). Nunca desce a subclasse nem
    cruza com porte do estabelecimento: num município isso pode apontar uma empresa.

    Mesma regra do estoque (macro efeito_no_saldo), então a soma do saldo por grupamento é
    igual ao saldo_consolidado do mart_estoque (test_fluxo_confere_estoque), e as contagens
    do município do boletim batem com o mart_caged_reconciliado (test_fluxo_confere_reconciliado).

    Subclasse 9999999 = não identificada no CAGED; não é a divisão 99 da CNAE (organismos
    internacionais). Vira divisao_cnae 'NI'.
#}

with eventos as (
    {{ efeito_no_saldo(['subgrupamento', 'subclasse']) }}
),

com_divisao as (
    select
        *,
        case
            when subclasse is null or subclasse = 9999999 then 'NI'
            else lpad(cast(subclasse // 100000 as varchar), 2, '0')
        end as divisao_cnae
    from eventos
),

agregado as (
    select
        territorio,
        competencia_mov,
        grupamento,
        subgrupamento,
        divisao_cnae,
        {{ contagens_reconciliadas() }}
    from com_divisao
    group by 1, 2, 3, 4, 5
)

select
    a.territorio,
    a.competencia_mov,
    a.grupamento,
    a.subgrupamento,
    a.divisao_cnae,
    case when a.divisao_cnae = 'NI' then 'Não identificada' else d.descricao end as divisao_descricao,
    coalesce(a.admissoes, 0)     as admissoes,
    coalesce(a.desligamentos, 0) as desligamentos,
    a.saldo
from agregado a
left join {{ ref('cnae_divisoes') }} d on d.divisao = a.divisao_cnae
order by 1, 2, 3, 4, 5
