{{ config(materialized='table') }}

{#
    Estoque de emprego por território × grupamento × competência (F20, D11):

        estoque(t) = referência + Σ saldo de (ref, t]      para t >= ref
        estoque(t) = referência − Σ saldo de (t, ref]      para t <  ref

    "referência" é o estoque de referência do MTE ao fim de `competencia_referencia` (o
    arquivo de 2026 é o de 202512), somado por território × grupamento. É o que o painel do
    Novo CAGED faz: troca de referência desloca a série inteira, até 2020. As duas fórmulas
    viram uma só: referência + acumulado(t) − acumulado(ref). saldo_consolidado = MOV + FOR −
    EXC por competência de movimentação (macro efeito_no_saldo, mesma regra do
    mart_caged_reconciliado), com todos os retificadores carregados.

    - A série começa em var('estoque_inicio') (202001). Jan e fev/2020 de Socorro ficam 2 abaixo do
      painel: recuar até eles passa pelo saldo de 202003, cujo CAGEDMOV no FTP diverge do
      painel (docs/auditorias/2026-09-28-painel-vs-mart-socorro.md). Diferença aceita (F20).
    - estoque é NULL em território sem referência e enquanto a competência da referência não
      estiver carregada (uma referência à frente dos dados daria um nível errado).
    - Grupamento ausente no arquivo (sem vínculo, ou "Não Identificado") vale 0 na referência,
      e todo território com referência tem as seis linhas de grupamento.
    - taxa_variacao_mensal = saldo ÷ estoque do mês anterior (fração, não %); NULL se não
      houver estoque anterior ou se ele for 0.
    - Territórios: os ativos em seeds/territorios.csv (município ou UF).

    Marco zero manual de mar/2020 (F16): desativado, em models/marco_zero_desativado/.
#}

with eventos as (
    {{ efeito_no_saldo() }}
),

territorios_ativos as (
    select territorio, tipo from {{ ref('territorios') }} where ativo
),

referencia as (
    select t.territorio, r.grupamento, r.competencia_referencia, sum(r.estoque) as estoque
    from {{ ref('stg_estoque_referencia') }} r
    join territorios_ativos t
        on t.territorio = case when t.tipo = 'uf' then r.uf else r.codmun end
    group by 1, 2, 3
),

-- Competência da referência por território: existe se houver ao menos uma linha dele.
referencia_territorio as (
    select distinct territorio, competencia_referencia from referencia
),

competencias as (
    select cast(strftime(d, '%Y%m') as bigint) as competencia_mov
    from generate_series(
        date '2020-01-01',
        (select make_date(max(competencia_mov) // 100, cast(max(competencia_mov) % 100 as integer), 1)
         from {{ ref('stg_caged_movimentacoes') }}),
        interval 1 month
    ) as t(d)
),

ultima_competencia as (
    select max(competencia_mov) as ultima from competencias
),

-- Território com referência tem os seis grupamentos (como tinha com o marco zero): o arquivo
-- do MTE omite grupamento sem vínculo, e a região (mart_estoque_regiao) só soma quando todos
-- os membros têm a linha.
grupamentos as (
    select distinct territorio, grupamento from eventos  -- só ativos (efeito_no_saldo)
    union
    select rt.territorio, g.grupamento
    from referencia_territorio rt
    cross join (values ('Agropecuária'), ('Indústria'), ('Construção'), ('Comércio'),
                       ('Serviços'), ('Não Identificado')) as g(grupamento)
),

saldo as (
    select territorio, grupamento, competencia_mov, sum(efeito) as saldo_consolidado
    from eventos
    group by 1, 2, 3
),

serie as (
    select
        g.territorio,
        g.grupamento,
        c.competencia_mov,
        coalesce(s.saldo_consolidado, 0)          as saldo_consolidado,
        rt.competencia_referencia,
        coalesce(r.estoque, 0)                    as estoque_referencia
    from grupamentos g
    cross join competencias c
    left join saldo s
        on s.territorio = g.territorio and s.grupamento = g.grupamento
       and s.competencia_mov = c.competencia_mov
    left join referencia_territorio rt on rt.territorio = g.territorio
    left join referencia r
        on r.territorio = g.territorio and r.grupamento = g.grupamento
),

acumulado as (
    select
        *,
        sum(saldo_consolidado) over (
            partition by territorio, grupamento order by competencia_mov
            rows between unbounded preceding and current row
        ) as acumulado,
        sum(case when competencia_mov <= competencia_referencia then saldo_consolidado else 0 end)
            over (partition by territorio, grupamento) as acumulado_ate_referencia
    from serie
),

com_estoque as (
    select
        a.*,
        case
            when a.competencia_referencia is null
              or a.competencia_referencia > u.ultima
              or a.competencia_mov < {{ var('estoque_inicio') }} then null
            else a.estoque_referencia + a.acumulado - a.acumulado_ate_referencia
        end as estoque
    from acumulado a
    cross join ultima_competencia u
)

select
    territorio,
    grupamento,
    competencia_mov,
    saldo_consolidado,
    estoque,
    saldo_consolidado / nullif(
        lag(estoque) over (partition by territorio, grupamento order by competencia_mov), 0
    ) as taxa_variacao_mensal,
    competencia_referencia
from com_estoque
order by 1, 2, 3
