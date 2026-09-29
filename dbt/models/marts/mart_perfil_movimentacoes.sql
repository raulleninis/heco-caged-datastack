{#
    Perfil das movimentações RECONCILIADAS (MOV + FOR − EXC) por território × competência,
    em duas dimensões independentes: sexo e faixa etária (F19 parte 1; roteiro, seção 1.4).
    Uma linha por (dimensão, categoria); as categorias de uma dimensão somam o total do
    território no mês (test_perfil_confere_fluxo).

    Códigos do Novo CAGED: sexo 1 = homem, 3 = mulher. Faixas etárias as do painel do MTE.
    Recortes pequenos não são suprimidos aqui: a regra de base pequena é aplicada nos fatos
    do boletim, que marcam o recorte e não o interpretam.
#}

with eventos as (
    {{ efeito_no_saldo(['sexo', 'idade']) }}
),

categorizado as (
    select
        *,
        case sexo when 1 then 'Homem' when 3 then 'Mulher' else 'Não identificado' end as cat_sexo,
        case
            when idade is null then 'Não identificada'
            when idade <= 17 then 'Até 17'
            when idade <= 24 then '18 a 24'
            when idade <= 29 then '25 a 29'
            when idade <= 39 then '30 a 39'
            when idade <= 49 then '40 a 49'
            when idade <= 64 then '50 a 64'
            else '65 ou mais'
        end as cat_faixa
    from eventos
),

por_sexo as (
    select territorio, competencia_mov, 'sexo' as dimensao, cat_sexo as categoria,
           {{ contagens_reconciliadas() }}
    from categorizado
    group by 1, 2, 3, 4
),

por_faixa as (
    select territorio, competencia_mov, 'faixa_etaria' as dimensao, cat_faixa as categoria,
           {{ contagens_reconciliadas() }}
    from categorizado
    group by 1, 2, 3, 4
)

select
    territorio,
    competencia_mov,
    dimensao,
    categoria,
    coalesce(admissoes, 0)     as admissoes,
    coalesce(desligamentos, 0) as desligamentos,
    saldo
from (select * from por_sexo union all select * from por_faixa)
order by 1, 2, 3, 4
