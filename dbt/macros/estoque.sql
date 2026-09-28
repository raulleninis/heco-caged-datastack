{#
    Efeito de cada linha das três stagings no saldo (F16/D11), uma linha por evento e por
    território ATIVO a que ele pertence:

        MOV → +saldo_movimentacao      FOR → +saldo_movimentacao      EXC → −saldo_movimentacao

    O EXC preserva o sinal do evento excluído (test_exc_preserva_sinal_do_evento), por isso
    o efeito é o inverso. `competencia_arquivo` do MOV é a própria competência (um arquivo
    por competência). Compartilhado por ajuste_marco_zero, mart_estoque e os testes de
    estoque, para a regra existir num lugar só.

    Territórios (seeds/territorios.csv, F16 parte 2): tipo 'municipio' casa com o código de
    6 dígitos do município; tipo 'uf' casa com a UF, somando todos os municípios. Um mesmo
    evento aparece uma vez por território (em Socorro e em Sergipe, por exemplo). Só os
    ativos entram: ativar = mudar `ativo` para true, sem reprocessar nada.
#}
{% macro efeito_no_saldo() %}
    select t.territorio, e.grupamento, e.competencia_mov, e.competencia_arquivo, e.tipo, e.efeito
    from (
        select municipio, uf, grupamento, competencia_mov,
               competencia_mov as competencia_arquivo, 'MOV' as tipo,
               saldo_movimentacao as efeito
        from {{ ref('stg_caged_movimentacoes') }}

        union all

        select municipio, uf, grupamento, competencia_mov,
               competencia_arquivo, 'FOR',
               saldo_movimentacao
        from {{ ref('stg_caged_fora_do_prazo') }}

        union all

        select municipio, uf, grupamento, competencia_mov,
               competencia_arquivo, 'EXC',
               -saldo_movimentacao
        from {{ ref('stg_caged_exclusoes') }}
    ) e
    join {{ ref('territorios') }} t
        on t.ativo
       and cast(case when t.tipo = 'uf' then e.uf else e.municipio end as varchar) = t.territorio
{% endmacro %}
