{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='competencia_mov'
) }}

{% set columns = {
    "competencia_mov": {"raw": "competênciamov", "cast": "BIGINT"},
    "regiao": {"raw": "região", "cast": "BIGINT"},
    "uf": {"raw": "uf", "cast": "BIGINT"},
    "municipio": {"raw": "município", "cast": "BIGINT"},
    "secao": {"raw": "seção", "cast": "VARCHAR"},
    "subclasse": {"raw": "subclasse", "cast": "BIGINT"},
    "saldo_movimentacao": {"raw": "saldomovimentação", "cast": "BIGINT"},
    "cbo_2002_ocupacao": {"raw": "cbo2002ocupação", "cast": "BIGINT"},
    "categoria": {"raw": "categoria", "cast": "BIGINT"},
    "grau_de_instrucao": {"raw": "graudeinstrução", "cast": "BIGINT"},
    "idade": {"raw": "idade", "cast": "BIGINT"},
    "horas_contratuais": {"raw": "horascontratuais", "cast": "DOUBLE", "decimal": true},
    "raca_cor": {"raw": "raçacor", "cast": "BIGINT"},
    "sexo": {"raw": "sexo", "cast": "BIGINT"},
    "tipo_empregador": {"raw": "tipoempregador", "cast": "BIGINT"},
    "tipo_estabelecimento": {"raw": "tipoestabelecimento", "cast": "BIGINT"},
    "tipo_movimentacao": {"raw": "tipomovimentação", "cast": "BIGINT"},
    "tipo_de_deficiencia": {"raw": "tipodedeficiência", "cast": "BIGINT"},
    "ind_trab_intermitente": {"raw": "indtrabintermitente", "cast": "BIGINT"},
    "ind_trab_parcial": {"raw": "indtrabparcial", "cast": "BIGINT"},
    "salario": {"raw": "salário", "cast": "DOUBLE", "decimal": true},
    "tam_estab_jan": {"raw": "tamestabjan", "cast": "BIGINT"},
    "indicador_aprendiz": {"raw": "indicadoraprendiz", "cast": "BIGINT"},
    "origem_da_informacao": {"raw": "origemdainformação", "cast": "BIGINT"},
    "competencia_dec": {"raw": "competênciadec", "cast": "BIGINT"},
    "indicador_de_fora_do_prazo": {"raw": "indicadordeforadoprazo", "cast": "BIGINT"},
    "unidade_salario_codigo": {"raw": "unidadesaláriocódigo", "cast": "BIGINT"},
    "valor_salario_fixo": {"raw": "valorsaláriofixo", "cast": "DOUBLE", "decimal": true}
} %}

{#
    grupamento e subgrupamento seguem a Tabela 1 do MTE — "Grupamentos de Atividades
    Econômicas para divulgação da RAIS e do CAGED" — que mapeia as seções da CNAE 2.0.
    O agrupamento em 6 categorias (grupamento) já reproduzia essa tabela letra a letra;
    subgrupamento acrescenta o segundo nível dela, ausente até aqui.

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
    {% for alias, meta in columns.items() %}
        {% if meta.get('decimal') %}
        CAST(REPLACE({{ meta.raw }}, ',', '.') AS {{ meta.cast }}) as {{ alias }}{{ "," if not loop.last else "" }}
        {% else %}
        CAST({{ meta.raw }} AS {{ meta.cast }}) as {{ alias }}{{ "," if not loop.last else "" }}
        {% endif %}
    {% endfor %}
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
    CASE
        WHEN secao = 'A' THEN 'Agropecuária'
        WHEN secao IN ('B','C','D','E') THEN 'Indústria'
        WHEN secao = 'F' THEN 'Construção'
        WHEN secao = 'G' THEN 'Comércio'
        WHEN secao IN ('H','I','J','K','L','M','N','O','P','Q','R','S','T','U') THEN 'Serviços'
        ELSE 'Não Identificado'
    END as grupamento,
    CASE
        WHEN secao = 'A' THEN 'Agropecuária'
        WHEN secao = 'C' THEN 'Indústrias de Transformação'
        WHEN secao IN ('B','D','E') THEN 'Indústria geral'
        WHEN secao = 'F' THEN 'Construção'
        WHEN secao = 'G' THEN 'Comércio, reparação de veículos automotores e motocicletas'
        WHEN secao = 'H' THEN 'Transporte, armazenagem e correio'
        WHEN secao = 'I' THEN 'Alojamento e alimentação'
        WHEN secao IN ('J','K','L','M','N') THEN 'Informação, comunicação e atividades financeiras, imobiliárias, profissionais e administrativas'
        WHEN secao IN ('O','P','Q') THEN 'Administração pública, defesa, seguridade social, educação, saúde humana e serviços sociais'
        WHEN secao IN ('R','S','U') THEN 'Outros serviços'
        WHEN secao = 'T' THEN 'Serviços domésticos'
        ELSE 'Não Identificado'
    END as subgrupamento
from filtrado
