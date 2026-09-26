{#
    Definições compartilhadas pelas três staging do CAGED (MOV, FOR, EXC — F12).
    Os três arquivos têm as mesmas 28 colunas; o EXC tem 2 a mais (caged_colunas_exc).
    Ficam aqui, e não copiadas em cada modelo, para as três não divergirem.

    O source lê tudo como VARCHAR (all_varchar=true, ver _sources.yml); o CAST real
    é feito aqui, de forma explícita e estável entre competências (F09).
#}

{% macro caged_colunas() %}
    {{ return({
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
    }) }}
{% endmacro %}

{# O EXC acrescenta a competência da exclusão e o indicador de exclusão. #}
{% macro caged_colunas_exc() %}
    {% set cols = caged_colunas() %}
    {% do cols.update({
        "competencia_exc": {"raw": "competênciaexc", "cast": "BIGINT"},
        "indicador_de_exclusao": {"raw": "indicadordeexclusão", "cast": "BIGINT"}
    }) %}
    {{ return(cols) }}
{% endmacro %}

{# Lista de CAST ... AS alias, na ordem do dicionário. #}
{% macro caged_cast_colunas(columns) %}
    {%- for alias, meta in columns.items() %}
        {%- if meta.get('decimal') %}
        CAST(REPLACE({{ meta.raw }}, ',', '.') AS {{ meta.cast }}) as {{ alias }}
        {%- else %}
        CAST({{ meta.raw }} AS {{ meta.cast }}) as {{ alias }}
        {%- endif %}{{ "," if not loop.last }}
    {%- endfor %}
{% endmacro %}

{#
    grupamento e subgrupamento seguem a Tabela 1 do MTE — "Grupamentos de Atividades
    Econômicas para divulgação da RAIS e do CAGED" — que mapeia as seções da CNAE 2.0.
#}
{% macro caged_grupamento(secao) %}
    CASE
        WHEN {{ secao }} = 'A' THEN 'Agropecuária'
        WHEN {{ secao }} IN ('B','C','D','E') THEN 'Indústria'
        WHEN {{ secao }} = 'F' THEN 'Construção'
        WHEN {{ secao }} = 'G' THEN 'Comércio'
        WHEN {{ secao }} IN ('H','I','J','K','L','M','N','O','P','Q','R','S','T','U') THEN 'Serviços'
        ELSE 'Não Identificado'
    END
{% endmacro %}

{% macro caged_subgrupamento(secao) %}
    CASE
        WHEN {{ secao }} = 'A' THEN 'Agropecuária'
        WHEN {{ secao }} = 'C' THEN 'Indústrias de Transformação'
        WHEN {{ secao }} IN ('B','D','E') THEN 'Indústria geral'
        WHEN {{ secao }} = 'F' THEN 'Construção'
        WHEN {{ secao }} = 'G' THEN 'Comércio, reparação de veículos automotores e motocicletas'
        WHEN {{ secao }} = 'H' THEN 'Transporte, armazenagem e correio'
        WHEN {{ secao }} = 'I' THEN 'Alojamento e alimentação'
        WHEN {{ secao }} IN ('J','K','L','M','N') THEN 'Informação, comunicação e atividades financeiras, imobiliárias, profissionais e administrativas'
        WHEN {{ secao }} IN ('O','P','Q') THEN 'Administração pública, defesa, seguridade social, educação, saúde humana e serviços sociais'
        WHEN {{ secao }} IN ('R','S','U') THEN 'Outros serviços'
        WHEN {{ secao }} = 'T' THEN 'Serviços domésticos'
        ELSE 'Não Identificado'
    END
{% endmacro %}
