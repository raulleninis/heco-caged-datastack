{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='competencia_arquivo'
) }}

{#
    CAGEDFOR: movimentações declaradas FORA DO PRAZO (F12). Somam ao saldo registrado.

    A chave NÃO é competencia_mov: um arquivo CAGEDFOR de uma competência de declaração
    traz movimentações de VÁRIAS competências anteriores (retroage ~12 meses). Os
    arquivos são incrementais entre si (sem linhas repetidas), então a unidade de carga
    é o arquivo: competencia_arquivo = o AAAAMM do nome. Reprocessar um arquivo apaga as
    linhas dele e as reinsere (idempotente); nunca soma por cima.

    Mesmo desenho de memória da staging MOV: um arquivo por vez (--vars
    '{"competencia_arquivo": "AAAAMM"}'). Estes arquivos são pequenos (~8 MB extraídos).
#}

{% set columns = caged_colunas() %}

with source as (

    select *
    from {{ source('caged_raw', 'caged_fora_do_prazo') }}

),

casted as (

    select
    {{ caged_cast_colunas(columns) }},
        CAST(regexp_extract(filename, 'CAGEDFOR([0-9]{6})\.txt', 1) AS BIGINT) as competencia_arquivo
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
