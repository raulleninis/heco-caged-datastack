-- Falha se, na competência da referência, o estoque do mart não for exatamente o do arquivo
-- do MTE somado por território × grupamento (F20). Pega erro de âncora: grupamento mapeado
-- errado (subclasse → seção), território casado pelo código errado, fórmula para trás/para
-- frente deslocada de um mês.

with territorios_ativos as (
    select territorio, tipo from {{ ref('territorios') }} where ativo
),

referencia as (
    select t.territorio, r.grupamento, r.competencia_referencia, sum(r.estoque) as estoque
    from {{ ref('stg_estoque_referencia') }} r
    join territorios_ativos t
        on t.territorio = case when t.tipo = 'uf' then r.uf else r.codmun end
    group by 1, 2, 3
)

select r.territorio, r.grupamento, r.competencia_referencia, r.estoque as estoque_referencia, e.estoque
from referencia r
left join {{ ref('mart_estoque') }} e
    on e.territorio = r.territorio and e.grupamento = r.grupamento
   and e.competencia_mov = r.competencia_referencia
where e.estoque is distinct from r.estoque
  -- referência à frente dos dados carregados: o mart deixa NULL de propósito
  and r.competencia_referencia <= (select max(competencia_mov) from {{ ref('stg_caged_movimentacoes') }})
