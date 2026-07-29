{{ config(materialized='view') }}

{% set exclude_cols = var('caged_exclude_columns', []) %}

{% set columns = {
    "competencia_mov": "competênciamov",
    "regiao": "região",
    "uf": "uf",
    "municipio": "município",
    "secao": "seção",
    "subclasse": "subclasse",
    "saldo_movimentacao": "saldomovimentação",
    "cbo_2002_ocupacao": "cbo2002ocupação",
    "categoria": "categoria",
    "grau_de_instrucao": "graudeinstrução",
    "idade": "idade",
    "horas_contratuais": "CAST(REPLACE(horascontratuais, ',', '.') AS DOUBLE)",
    "raca_cor": "raçacor",
    "sexo": "sexo",
    "tipo_empregador": "tipoempregador",
    "tipo_estabelecimento": "tipoestabelecimento",
    "tipo_movimentacao": "tipomovimentação",
    "tipo_de_deficiencia": "tipodedeficiência",
    "ind_trab_intermitente": "indtrabintermitente",
    "ind_trab_parcial": "indtrabparcial",
    "salario": "CAST(REPLACE(salário, ',', '.') AS DOUBLE)",
    "tam_estab_jan": "tamestabjan",
    "indicador_aprendiz": "indicadoraprendiz",
    "origem_da_informacao": "origemdainformação",
    "competencia_dec": "competênciadec",
    "indicador_de_fora_do_prazo": "indicadordeforadoprazo",
    "unidade_salario_codigo": "unidadesaláriocódigo",
    "valor_salario_fixo": "CAST(REPLACE(valorsaláriofixo, ',', '.') AS DOUBLE)",
    "grupamento": "CASE
        WHEN seção = 'A' THEN 'Agropecuária'
        WHEN seção IN ('B','C','D','E') THEN 'Indústria'
        WHEN seção = 'F' THEN 'Construção'
        WHEN seção = 'G' THEN 'Comércio'
        WHEN seção IN ('H','I','J','K','L','M','N','O','P','Q','R','S','T','U') THEN 'Serviços'
        ELSE 'Não Identificado'
    END"
} %}

with source as (

    select *
    from read_csv_auto('/data/raw/extraido/*.txt', delim=';', union_by_name=true)

),

filtrado as (

    select *
    from source
    where uf = 28
      and município = 280480

)

select
{% for alias, expr in columns.items() if alias not in exclude_cols %}
    {{ expr }} as {{ alias }}{{ "," if not loop.last else "" }}
{% endfor %}
from filtrado
