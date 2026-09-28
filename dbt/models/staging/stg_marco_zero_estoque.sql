{{ config(materialized='table') }}

{#
    Marco zero do estoque (F16/D11), lido de marco-zero/estoque/*.csv (git). Tabela, não
    view: quem consulta o warehouse (DBeaver, boletim) não precisa enxergar /marco-zero.

    competencia_marco_zero: a competência cujo FIM é o marco (2020-03-31 → 202003). As
    movimentações entram a partir da seguinte.
    retificacoes_ate: último arquivo FOR/EXC que o painel já tinha incorporado na coleta.
    Linhas de FOR/EXC com competência até a do marco só ajustam o marco se vierem de arquivo
    POSTERIOR a este (ajuste_marco_zero); as anteriores já estão no número do painel.
#}

select
    cast(territorio as varchar)                                   as territorio,
    trim(grupamento)                                              as grupamento,
    cast(estoque as bigint)                                       as estoque,
    cast(data_referencia as date)                                 as data_referencia,
    cast(strftime(cast(data_referencia as date), '%Y%m') as bigint) as competencia_marco_zero,
    cast(retificacoes_ate as bigint)                              as retificacoes_ate,
    fonte,
    cast(coletado_em as date)                                     as coletado_em,
    regexp_extract(filename, '[^/]+$')                            as arquivo
from {{ source('marco_zero', 'estoque') }}
