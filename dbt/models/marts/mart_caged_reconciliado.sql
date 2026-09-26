{{ config(materialized='table') }}

{#
    Reconciliação do saldo por COMPETÊNCIA DE MOVIMENTAÇÃO (F12):

        consolidado = MOV (dentro do prazo) + FOR (fora do prazo) - EXC (exclusões)

    O CAGED recebe declarações fora do prazo e exclusões que corrigem meses já publicados,
    então o número só-MOV (mart_caged_mensal_grupamento) é PROVISÓRIO e, para competências
    recentes, subestimado. Este mart é o que reconcilia.

    Sinal das exclusões (D11, verificado nos dados): o EXC preserva o sinal do evento
    excluído (admissão excluída = +1). O EFEITO no saldo é o inverso, e é feito aqui:
        saldo_exclusoes = -(admissoes_excluidas - desligamentos_excluidos)

    Provisório x consolidado: o FOR retroage ~12 meses (F12). Uma competência com menos de
    `meses_para_consolidar` meses de defasagem em relação à última competência carregada
    ainda pode receber declarações fora do prazo: é 'provisório'. Depois disso só exclusões
    tardias podem mexer nela (o EXC retroage até 2020): 'consolidado' NÃO quer dizer imutável.
    O limite é ajustável: --vars '{"meses_para_consolidar": 18}'.

    As métricas de salário continuam só no mart_caged_mensal_grupamento (MOV): a mediana de
    quem entrou fora do prazo não se soma nem se subtrai da mediana do MOV.
#}

with eventos as (

    select competencia_mov, grupamento, saldo_movimentacao as saldo, 'MOV' as tipo
    from {{ ref('stg_caged_movimentacoes') }}

    union all

    select competencia_mov, grupamento, saldo_movimentacao, 'FOR'
    from {{ ref('stg_caged_fora_do_prazo') }}

    union all

    select competencia_mov, grupamento, saldo_movimentacao, 'EXC'
    from {{ ref('stg_caged_exclusoes') }}

),

por_grupo as (

    select
        competencia_mov,
        grupamento,
        count(*) filter (where tipo = 'MOV' and saldo = 1)  as admissoes_mov,
        count(*) filter (where tipo = 'MOV' and saldo = -1) as desligamentos_mov,
        count(*) filter (where tipo = 'FOR' and saldo = 1)  as admissoes_fora_prazo,
        count(*) filter (where tipo = 'FOR' and saldo = -1) as desligamentos_fora_prazo,
        count(*) filter (where tipo = 'EXC' and saldo = 1)  as admissoes_excluidas,
        count(*) filter (where tipo = 'EXC' and saldo = -1) as desligamentos_excluidos
    from eventos
    group by 1, 2

),

corte as (

    select max(competencia_mov) as ultima_competencia
    from {{ ref('stg_caged_movimentacoes') }}

),

calculado as (

    select
        g.competencia_mov,
        g.grupamento,

        g.admissoes_mov,
        g.desligamentos_mov,
        g.admissoes_mov - g.desligamentos_mov as saldo_mov,

        g.admissoes_fora_prazo,
        g.desligamentos_fora_prazo,
        g.admissoes_fora_prazo - g.desligamentos_fora_prazo as saldo_fora_prazo,

        g.admissoes_excluidas,
        g.desligamentos_excluidos,
        -(g.admissoes_excluidas - g.desligamentos_excluidos) as saldo_exclusoes,

        g.admissoes_mov + g.admissoes_fora_prazo - g.admissoes_excluidas as admissoes_consolidadas,
        g.desligamentos_mov + g.desligamentos_fora_prazo - g.desligamentos_excluidos as desligamentos_consolidados,

        c.ultima_competencia as ultima_competencia_carregada,
        (c.ultima_competencia // 100) * 12 + (c.ultima_competencia % 100)
          - ((g.competencia_mov // 100) * 12 + (g.competencia_mov % 100)) as defasagem_meses

    from por_grupo g
    cross join corte c

)

select
    competencia_mov,
    grupamento,
    admissoes_mov,
    desligamentos_mov,
    saldo_mov,
    admissoes_fora_prazo,
    desligamentos_fora_prazo,
    saldo_fora_prazo,
    admissoes_excluidas,
    desligamentos_excluidos,
    saldo_exclusoes,
    admissoes_consolidadas,
    desligamentos_consolidados,
    admissoes_consolidadas - desligamentos_consolidados as saldo_consolidado,
    ultima_competencia_carregada,
    defasagem_meses,
    case
        when defasagem_meses < {{ var('meses_para_consolidar', 12) }} then 'provisório'
        else 'consolidado'
    end as situacao
from calculado
order by 1, 2
