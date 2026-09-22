# F09 · Testes de qualidade ampliados

| | |
|---|---|
| **Esforço** | M (meio dia) |
| **Fase** | pré-produção |
| **Depende de** | [F05](F05-corrigir-salario-medio.md) |
| **Resolve** | Achados D e F |

## Problema

O projeto tem **6 testes**, todos rasos:

| modelo | testes |
|---|---|
| `stg_caged_movimentacoes` | `not_null` em 4 colunas, `accepted_values` em `uf`, `municipio`, `grupamento` |
| `mart_caged_mensal_grupamento` | `not_null` em 3 colunas |

Nenhum deles teria pego o erro de salário da [F05](F05-corrigir-salario-medio.md) —
**R$ 7.265,68 passou por todos os 6 testes sem levantar nada**, porque nenhum teste
olha para valor.

E os testes que existem testam o que **não pode dar errado**: `uf = 28` e
`municipio = 280480` são *filtros escritos no próprio modelo*. O teste confirma que
o `WHERE` funciona — não que o dado está bom.

### Maquinário morto

```bash
$ grep -rn "caged_exclude_columns" .
dbt/models/staging/stg_caged_movimentacoes.sql:3
```

A var `caged_exclude_columns` ([linha 3](../../dbt/models/staging/stg_caged_movimentacoes.sql#L3))
nunca é definida em lugar nenhum. O `if alias not in exclude_cols` na
[linha 61](../../dbt/models/staging/stg_caged_movimentacoes.sql#L61) nunca exclui nada.
É complexidade Jinja que não paga aluguel: ou passa a ser usada, ou sai.

## Escopo

### Testes que pegam erro de verdade

1. **`saldo_movimentacao` só aceita `1` e `-1`** — o `README` afirma isso, e a mart
   inteira depende disso (`count(*) filter (where saldo_movimentacao = 1)`).
   Se aparecer um `0` ou `2`, `admissoes + desligamentos != count(*)` e ninguém percebe.
2. **Unicidade do grão da mart**: `(competencia_mov, grupamento)` deve ser único.
   Hoje nada garante.
3. **Coerência aritmética**: `saldo_liquido = admissoes - desligamentos`.
   Teste singular em SQL, barato, pega regressão de refatoração.
4. **Faixa de salário**: `salario_medio_admissao` entre limites plausíveis —
   este é o teste que teria pego a [F05](F05-corrigir-salario-medio.md).
5. **`accepted_values` em `unidade_salario_codigo`**, para detectar unidade nova na fonte.
6. **`relationships`** entre mart e staging por `competencia_mov`.

### Contrato com a fonte

7. Declarar os `.txt` como **`source`** com `freshness`, em vez de um
   `read_csv_auto` solto dentro do modelo. Hoje não há nenhuma declaração de origem —
   o dbt não sabe de onde o dado vem, e o lineage do `dbt docs` fica cego.
8. **Tipos explícitos** no `read_csv_auto`: hoje não há `columns=` nem `sample_size=`,
   então o DuckDB **infere** tipos a partir de uma amostra. Com `union_by_name=true`,
   uma competência que inferir `subclasse` como `VARCHAR` e outra como `BIGINT`
   produz erro — ou pior, coerção silenciosa. Fixar o schema transforma
   "mudou a fonte" em erro alto e imediato.

### Materialização

9. Reavaliar `materialized: view` na staging. Sendo view, **cada consulta relê 2,5 GB**
   de `.txt`. Como `table`, lê uma vez por `dbt run` — e destrava a limpeza do raw
   na [F07](F07-retencao-e-permissoes.md).

### Limpeza

10. Remover `caged_exclude_columns`, ou definir a var e documentar para que serve.

## Critério de aceite

```bash
dbt test --project-dir /dbt --profiles-dir /dbt
# -> todos passam
```

E o teste do teste — **injete o defeito e confirme que ele é pego**:

```sql
-- reintroduza o registro de 356.620,00 na base e rode dbt test
-- -> o teste de faixa de salário DEVE falhar
```

Um conjunto de testes que nunca falhou não é um conjunto de testes, é decoração.
