# Marco zero do estoque de emprego (F16 / D11)

Único insumo manual do projeto: o estoque de emprego formal ao **fim de mar/2020**, por território ×
grupamento. O estoque de cada mês é calculado aplicando as movimentações (`MOV + FOR − EXC`) a partir de
**abr/2020**. Fonte, metodologia, conferência e regra de ajuste estão em [FONTE.md](FONTE.md).

## Conteúdo

| caminho | o que é |
|---|---|
| `estoque/<codigo>_<nome>.csv` | um arquivo por território, no formato que o dbt lê (`stg_marco_zero_estoque`) |
| `validacao/<codigo>_estoque_painel.csv` | estoque do painel em meses posteriores, só para conferência (`test_estoque_confere_painel`) |
| `Caged Mar 2020.csv`, `validacao/Caged Estoque ....csv` | originais do painel do MTE |
| `Caged Jan 2020.xlsx` | original de jan/2020, usado só como prova cruzada |
| `normalizar.py` | gera `estoque/` e `validacao/*_estoque_painel.csv` a partir dos originais |
| `FONTE.md` | de onde veio, quando, recorte e conferência |

Esta pasta é montada só para leitura em `/marco-zero` no container do pipeline.

## Formato

Uma linha por grupamento, sempre os **seis** do código:

| coluna | |
|---|---|
| `territorio` | código de 6 dígitos do município, ou `28` para Sergipe |
| `grupamento` | `Agropecuária`, `Indústria`, `Construção`, `Comércio`, `Serviços`, `Não Identificado` |
| `estoque` | valor do painel (ausente = 0) |
| `data_referencia` | `2020-03-31` |
| `retificacoes_ate` | último arquivo FOR/EXC já incorporado pelo painel na coleta (`202607`) |
| `fonte` | resumo da origem; os detalhes estão em `FONTE.md` |
| `coletado_em` | data da consulta ao painel |

## Adicionar um território

Crie `estoque/<codigo>_<nome>.csv` com os seis grupamentos na mesma data de referência e acrescente
uma linha à tabela de territórios de `FONTE.md`. Não é preciso reprocessar o histórico. O estoque só
aparece no `mart_estoque` quando o território tiver movimentação na staging (F16, parte 2).

Para conferir outro território ou novos meses, acrescente ao original do painel e rode
`python3 marco-zero/normalizar.py`.

## Regras

- O valor manual é **imutável**. Retificações que cheguem depois da coleta entram por uma tabela
  **calculada**, com a regra descrita em `FONTE.md`.
- Esta pasta vai para o git. O marco zero precisa sobreviver a uma reconstrução do warehouse (D03).
- Sem marco zero para um território, nada quebra: ele mantém o fluxo, e estoque e taxa ficam `NULL`.
