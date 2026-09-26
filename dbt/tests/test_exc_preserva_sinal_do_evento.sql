-- Trava a premissa mais perigosa da F12 (D11): a coluna saldo_movimentacao do CAGEDEXC
-- PRESERVA o sinal do evento excluído (uma admissão excluída vem com +1). Se um dia o PDET
-- passar a entregar o EXC já invertido, somar/subtrair daria o sinal errado em silêncio.
--
-- Referência: o sinal que cada tipo_movimentacao tem no MOV (o tipo define se é admissão ou
-- desligamento). Falha se algum EXC tiver o sinal contrário ao do MOV para o mesmo tipo.

with sinal_no_mov as (
    select tipo_movimentacao, min(saldo_movimentacao) as sinal
    from {{ ref('stg_caged_movimentacoes') }}
    group by 1
    having min(saldo_movimentacao) = max(saldo_movimentacao)
)

select
    e.competencia_arquivo,
    e.competencia_mov,
    e.tipo_movimentacao,
    e.saldo_movimentacao as saldo_no_exc,
    s.sinal as saldo_esperado_pelo_mov
from {{ ref('stg_caged_exclusoes') }} e
join sinal_no_mov s using (tipo_movimentacao)
where e.saldo_movimentacao != s.sinal
