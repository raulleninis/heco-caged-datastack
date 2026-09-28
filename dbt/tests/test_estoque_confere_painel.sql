{{ config(severity='warn') }}

-- Confere o estoque calculado com o do painel do MTE (marco-zero/validacao/, critério 7 da
-- F16). Em 28/09/2026: 84 de 84 combinações (14 competências × 6 grupamentos) idênticas.
--
-- O painel é uma foto: só incorporava os arquivos até `retificacoes_ate`. Por isso o
-- estoque é recalculado AQUI só com esses arquivos, e não lido do mart_estoque (que inclui
-- retificadores posteriores e, com o tempo, se afasta da foto legitimamente). Assim o
-- teste continua válido para sempre, e só falha se os dados de então mudarem: um MOV
-- histórico republicado e reprocessado, um bug na regra ou um marco zero errado.
--
-- warn (D04): diverge de uma publicação externa, não prova que o número está errado.
-- Para achar onde começa a divergência, ordene por competencia.

with painel as (
    select
        territorio,
        grupamento,
        cast(competencia as bigint)      as competencia,
        cast(estoque as bigint)          as estoque_painel,
        cast(retificacoes_ate as bigint) as retificacoes_ate
    from {{ source('marco_zero', 'validacao_painel') }}
),

eventos as (
    {{ efeito_no_saldo() }}
),

marco as (
    select territorio, grupamento, estoque, competencia_marco_zero, retificacoes_ate
    from {{ ref('stg_marco_zero_estoque') }}
),

calculado as (
    select
        p.territorio,
        p.grupamento,
        p.competencia,
        p.estoque_painel,
        m.estoque + coalesce(sum(e.efeito), 0) as estoque_calculado
    from painel p
    join marco m
        on m.territorio = p.territorio and m.grupamento = p.grupamento
    left join eventos e
        on e.territorio = p.territorio
       and e.grupamento = p.grupamento
       and e.competencia_arquivo <= p.retificacoes_ate
       and (
            -- fluxo depois do marco, até a competência conferida
            (e.competencia_mov > m.competencia_marco_zero and e.competencia_mov <= p.competencia)
            -- ajuste do marco: retificação de competência até o marco, vinda de arquivo
            -- posterior à coleta do marco mas anterior à foto do painel
         or (e.tipo != 'MOV' and e.competencia_mov <= m.competencia_marco_zero
             and e.competencia_arquivo > m.retificacoes_ate)
       )
    group by 1, 2, 3, 4, m.estoque
)

select
    territorio,
    grupamento,
    competencia,
    estoque_painel,
    estoque_calculado,
    estoque_calculado - estoque_painel as diferenca
from calculado
where estoque_calculado != estoque_painel
order by competencia, grupamento
