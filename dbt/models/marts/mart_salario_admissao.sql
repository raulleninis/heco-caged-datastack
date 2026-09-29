{#
    Salário de admissão por território × competência, todos os grupamentos juntos (F19
    parte 1; roteiro, seção 1.4). A mediana do território não se obtém das medianas por
    grupamento do mart_caged_mensal_grupamento, por isso é calculada aqui sobre os registros.

    Mesmas regras da D05 e do mart_caged_mensal_grupamento: só MOV (FOR e EXC não entram
    na distribuição salarial), só admissões, unidade_salario_codigo = 5 (mensal) e
    valor_salario_fixo > 0. Mediana é a referência; média, para comparação.
#}

with admissoes as (
    select t.territorio, m.competencia_mov, m.valor_salario_fixo
    from {{ ref('stg_caged_movimentacoes') }} m
    join {{ ref('territorios') }} t
        on t.ativo
       and cast(case when t.tipo = 'uf' then m.uf else m.municipio end as varchar) = t.territorio
    where m.saldo_movimentacao = 1
      and m.unidade_salario_codigo = 5
      and m.valor_salario_fixo > 0
)

select
    territorio,
    competencia_mov,
    count(*)                                                                  as admissoes_com_salario_valido,
    round(percentile_disc(0.5) within group (order by valor_salario_fixo), 2) as salario_mediano_admissao,
    round(avg(valor_salario_fixo), 2)                                         as salario_medio_admissao
from admissoes
group by 1, 2
order by 1, 2
