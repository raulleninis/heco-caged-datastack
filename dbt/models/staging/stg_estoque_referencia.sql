{{ config(materialized='table') }}

{#
    Estoque de referência do MTE (F20), a âncora do mart_estoque. O painel do Novo CAGED
    parte deste arquivo (estoque ao fim de dezembro do ano anterior) e soma ou subtrai os
    saldos: conferido em 01/10/2026 nos cinco territórios, em 202003 e 202608.

    O arquivo vem por subclasse CNAE, sem seção: a seção sai da divisão (2 primeiros dígitos
    da subclasse com 7 dígitos, seed cnae_divisoes), e o grupamento da mesma macro das
    stagings do CAGED. O arquivo traz a subclasse sem o zero à esquerda (111302 = 0111302).
    A subclasse 9999999 é "não identificada" (seção Z nos microdados), não a divisão 99
    (organismos internacionais): sem seção, cai em 'Não Identificado' como no CAGED.
#}

with bruto as (
    select
        ano_referencia,
        competencia_referencia,
        codmun,
        lpad(trim(subclasse), 7, '0') as subclasse,
        estoque
    from {{ source('warehouse', 'estoque_referencia') }}
)

select
    b.ano_referencia,
    b.competencia_referencia,
    b.codmun,
    left(b.codmun, 2)                    as uf,
    b.subclasse,
    d.secao,
    {{ caged_grupamento('d.secao') }}    as grupamento,
    b.estoque
from bruto b
left join {{ ref('cnae_divisoes') }} d
    on d.divisao = left(b.subclasse, 2) and b.subclasse != '9999999'
