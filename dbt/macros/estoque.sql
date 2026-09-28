{#
    Efeito de cada linha das três stagings no saldo (F16/D11), uma linha por evento:

        MOV → +saldo_movimentacao      FOR → +saldo_movimentacao      EXC → −saldo_movimentacao

    O EXC preserva o sinal do evento excluído (test_exc_preserva_sinal_do_evento), por isso
    o efeito é o inverso. `competencia_arquivo` do MOV é a própria competência (um arquivo
    por competência). Compartilhado por ajuste_marco_zero, mart_estoque e os testes de
    estoque, para a regra existir num lugar só.

    territorio: hoje o código do município, porque a staging só guarda Socorro (F16 parte 1).
    Com a persistência de uf=28 (parte 2) passa a vir de territorios.csv.
#}
{% macro efeito_no_saldo() %}
    select cast(municipio as varchar) as territorio, grupamento, competencia_mov,
           competencia_mov as competencia_arquivo, 'MOV' as tipo,
           saldo_movimentacao as efeito
    from {{ ref('stg_caged_movimentacoes') }}

    union all

    select cast(municipio as varchar), grupamento, competencia_mov,
           competencia_arquivo, 'FOR',
           saldo_movimentacao
    from {{ ref('stg_caged_fora_do_prazo') }}

    union all

    select cast(municipio as varchar), grupamento, competencia_mov,
           competencia_arquivo, 'EXC',
           -saldo_movimentacao
    from {{ ref('stg_caged_exclusoes') }}
{% endmacro %}
