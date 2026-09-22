# F16 · Estoque a partir do marco zero

| | |
|---|---|
| **Esforço** | L (1 a 3 dias) |
| **Fase** | produção |
| **Depende de** | [F12](F12-for-exc-reconciliacao.md), [F09](F09-testes-de-qualidade.md) (staging materializada) |
| **Decisões associadas** | [D11](../decisoes/D11-estoque-de-emprego.md), [D06](../decisoes/D06-retencao-de-dados-brutos.md), [D03](../decisoes/D03-onde-guardar-os-dados.md) |

## Objetivo

Produzir o **estoque de emprego** por município × grupamento e, com ele, a taxa de
variação, a partir de um marco zero manual (fim de dez/2019) e das movimentações
`MOV + FOR − EXC`. Funciona hoje **só com Socorro** e aceita Aracaju e Sergipe depois,
**apenas inserindo dados**.

*Nada disto foi aplicado ao código.*

## O problema de arquitetura que esta fatia resolve

Hoje a staging filtra `município = 280480` **dentro do SQL** e lê o raw por glob. Isso
tem duas consequências para o estoque:

1. **Adicionar Aracaju exigiria reprocessar todo o histórico**, porque o raw é apagado
   ([D06](../decisoes/D06-retencao-de-dados-brutos.md)) e as linhas de Aracaju nunca
   foram guardadas.
2. **Sem o raw, não dá para recalcular o estoque**, que é cumulativo.

A saída é **persistir as linhas de Sergipe** (`uf = 28`), já filtradas, e tratar o
município como configuração. Medi nos arquivos de jan a mai de 2026:

| | linhas/mês (média) |
|---|---|
| Brasil | ~4,5 milhões |
| **Sergipe** | **~26 mil** (~0,6% do Brasil) |
| Aracaju | ~14 mil |
| Socorro | ~2 mil |

Para ~80 competências, são da ordem de **2 milhões de linhas** em Sergipe. O tamanho em
disco e a memória durante o run **precisam ser medidos** na VM (830 MiB compartilhados);
não medi.

## Escopo

### 1. Configuração de territórios

Seed `territorios.csv`: código de 6 dígitos (o que aparece nos arquivos), nome, tipo
(`municipio` ou `uf`), `ativo`. Começa com Socorro (`280480`). Aracaju (`280030`) e
Sergipe entram depois por uma linha, sem código novo.

### 2. Marco zero

Seed `marco_zero_estoque.csv`, versionado no git:

| coluna | |
|---|---|
| `territorio` | código de 6 dígitos |
| `grupamento` | mesmas seis categorias do código, incluindo "Não Identificado" |
| `estoque` | valor manual |
| `data_referencia` | `2019-12-31` |
| `fonte` | **obrigatória**: de onde veio o número e a metodologia |
| `coletado_em` | data em que foi obtido |

O valor **nunca é editado** para absorver retificadores; isso é calculado (item 4).

### 3. Persistir as movimentações, por arquivo

Tabela `movimentacoes` (no warehouse) com as linhas de `uf = 28` de **todos** os tipos,
mais:

| coluna | |
|---|---|
| `tipo_arquivo` | `MOV`, `FOR` ou `EXC` |
| `arquivo_origem` | nome do arquivo (por exemplo `CAGEDEXC202607`) |
| `sha256` | do arquivo baixado |

Reprocessar um arquivo **substitui** as linhas dele (apaga por `arquivo_origem` e
insere), nunca soma por cima. Isso torna o estoque idempotente. Só as colunas da EXC
`competenciaexc` e `indicadordeexclusao` são exclusivas daquele tipo.

Cuidado herdado da F12: os três tipos **não podem** cair na mesma pasta lida por glob,
ou FOR e EXC são somados como MOV em silêncio.

### 4. Efeito no saldo e ajuste do marco zero

```
efeito_no_saldo = +saldo_movimentacao   se tipo_arquivo em (MOV, FOR)
                  −saldo_movimentacao   se tipo_arquivo = EXC
```

O sinal da EXC está **confirmado nos dados**
([D11](../decisoes/D11-estoque-de-emprego.md#sinal-das-exclusões)): a coluna preserva o
sinal do evento excluído, então o efeito é o inverso.

Linhas de FOR/EXC com `competencia_mov < 2020-01` alimentam uma tabela derivada
`ajuste_marco_zero` (por território × grupamento). Nas duas amostras que examinei ela
sairia vazia, mas a regra fica.

### 5. Mart de estoque

`mart_estoque`, uma linha por `(territorio, grupamento, competencia)`:

- `saldo_consolidado` do mês (com o efeito acima);
- `estoque = marco_zero + ajuste + acumulado do saldo`, **`NULL` se não houver marco zero**;
- `taxa_variacao_mensal = saldo ÷ estoque do mês anterior`, `NULL` idem.

**Sem marco zero para um território, nada quebra:** ele mantém fluxo, e estoque e taxa
ficam `NULL`.

### 6. Boletim

Os campos de estoque e taxa **só aparecem quando existem**, com a nota "estimativa a
partir de marco zero". Um território sem marco zero **não impede a geração** do boletim
nem o envio da [F15](F15-entrega-por-email-e-arquivo.md).

### 7. Testes

| teste | severidade |
|---|---|
| **Continuidade:** existe `CAGEDMOV` para cada competência desde 202001, sem lacuna | `error` |
| **Sinal da EXC:** admissões excluídas têm efeito `−1`; desligamentos excluídos, `+1` | `error` |
| Estoque nunca negativo | `error` |
| Linhas de FOR/EXC com competência anterior a 2020 | `warn` (informa que o ajuste do marco zero foi acionado) |
| Território ativo sem marco zero | `warn` |
| Unicidade de `arquivo_origem` por tipo e competência | `error` |

## Fora de escopo

- Estoque por sexo, raça/cor, ocupação ou faixa etária (decidido em
  [D11](../decisoes/D11-estoque-de-emprego.md): essas desagregações usam só fluxo).
- Obter os valores do marco zero.
- O painel autenticado e o envio ([F15](F15-entrega-por-email-e-arquivo.md)).

## Critério de aceite

1. Com **só Socorro**, `mart_estoque` traz estoque e taxa para cada grupamento.
2. **Adicionar Aracaju** = uma linha em `territorios.csv` + linhas em
   `marco_zero_estoque.csv`. **Sem reprocessar o histórico**, Aracaju aparece.
3. Território **sem marco zero**: fluxo presente, estoque `NULL`, boletim gerado.
4. **Reprocessar o mesmo arquivo duas vezes** não altera o estoque.
5. **Apagar o `.duckdb` e reconstruir** dá o mesmo estoque (o marco zero vem do git).
6. **Fixture de exclusão:** uma exclusão de admissão reduz o estoque em 1.
7. Comparar o **saldo mensal consolidado** com o painel oficial do PDET para o mesmo
   município e competência (validação do fluxo; o nível continua sem validação).
