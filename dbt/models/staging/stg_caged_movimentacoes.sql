{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='competencia_mov'
) }}

{% set columns = caged_colunas() %}

{#
    As colunas, o CAST e o grupamento/subgrupamento (Tabela 1 do MTE) vêm de
    macros/caged.sql, compartilhadas com a staging de FOR e de EXC (F12).

    O source (_sources.yml) lê tudo como VARCHAR (all_varchar=true) — desativa
    a inferência de tipo por amostragem do DuckDB, que com union_by_name=true
    podia inferir tipos diferentes para a mesma coluna entre competências
    (ex.: subclasse como BIGINT numa, VARCHAR noutra) e gerar erro ou coerção
    silenciosa. Os CASTs abaixo fazem a conversão real, de forma explícita
    e estável entre competências (ver F09).

    Materialização incremental (não table): cada .txt bruto tem ~450-500MB
    (o Brasil inteiro; filtramos ~1.500 linhas de N. Sra. do Socorro). Ler
    todas as competências via glob de uma vez ("*.txt") estourava memória —
    validado em runtime: funcionava só com mem_limit >= 3g, mas o servidor
    de produção real tem 830MB RAM total (~484MB disponível, ver D02).
    ingest_caged.py chama `dbt run --vars '{"competencia_arquivo": "AAAAMM"}'`
    uma vez por competência baixada, processando um arquivo por vez — pico
    de memória cai de ~3GB (todas de uma vez) para ~500MB (um arquivo).
    unique_key + delete+insert tornam reprocessar uma competência idempotente
    (não duplica linhas se rodado de novo pra corrigir algo).
#}

with source as (

    select *
    from {{ source('caged_raw', 'caged_movimentacoes') }}

),

casted as (

    select
    {{ caged_cast_colunas(columns) }}
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
