{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='competencia_arquivo'
) }}

{#
    CAGEDEXC: exclusões de eventos já declarados (F12). SUBTRAEM do saldo registrado.

    Sinal (verificado nos dados em 22/09/2026, ver D11): a coluna saldo_movimentacao do
    EXC PRESERVA o sinal do evento excluído — uma admissão excluída vem com +1 e tem
    efeito -1. Esta staging guarda o valor COMO VEM; a inversão acontece no mart de
    reconciliação, e um teste trava isso (test_exc_preserva_sinal_do_evento).

    Mesma lógica de chave e de carga da staging de FOR: a unidade é o arquivo
    (competencia_arquivo). As exclusões retroagem até 202001. Tem 2 colunas a mais que
    o MOV: competencia_exc e indicador_de_exclusao.
#}

{% set columns = caged_colunas_exc() %}

with source as (

    select *
    from {{ source('caged_raw', 'caged_exclusoes') }}

),

casted as (

    select
    {{ caged_cast_colunas(columns) }},
        CAST(regexp_extract(filename, 'CAGEDEXC([0-9]{6})\.txt', 1) AS BIGINT) as competencia_arquivo
    from source

),

filtrado as (

    select *
    from casted
    where uf = 28
      and municipio = 280480

)

select
    *,
    {{ caged_grupamento('secao') }} as grupamento,
    {{ caged_subgrupamento('secao') }} as subgrupamento
from filtrado
