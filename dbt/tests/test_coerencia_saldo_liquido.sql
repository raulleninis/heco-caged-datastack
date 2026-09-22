-- Falha se saldo_liquido != admissoes - desligamentos em qualquer linha.
-- Teste barato que pega regressão de refatoração no mart (ver revisão de
-- 22/09/2026: F05 introduziu uma regressão exatamente nesse invariante,
-- que passou por todos os testes not_null existentes na época).

select
    competencia_mov,
    grupamento,
    admissoes,
    desligamentos,
    saldo_liquido,
    (admissoes - desligamentos) as saldo_esperado
from {{ ref('mart_caged_mensal_grupamento') }}
where saldo_liquido != (admissoes - desligamentos)
