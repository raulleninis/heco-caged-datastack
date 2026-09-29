-- F19: em cada dimensão do perfil (sexo, faixa etária), as categorias somam o total de
-- admissões, desligamentos e saldo do território no mês, igual ao mart_fluxo.
with fluxo as (
    select territorio, competencia_mov,
           sum(admissoes) as admissoes, sum(desligamentos) as desligamentos, sum(saldo) as saldo
    from {{ ref('mart_fluxo') }}
    group by 1, 2
),
perfil as (
    select territorio, competencia_mov, dimensao,
           sum(admissoes) as admissoes, sum(desligamentos) as desligamentos, sum(saldo) as saldo
    from {{ ref('mart_perfil_movimentacoes') }}
    group by 1, 2, 3
)
select p.*, f.admissoes as admissoes_fluxo, f.desligamentos as desligamentos_fluxo, f.saldo as saldo_fluxo
from perfil p
join fluxo f using (territorio, competencia_mov)
where p.admissoes != f.admissoes or p.desligamentos != f.desligamentos or p.saldo != f.saldo
