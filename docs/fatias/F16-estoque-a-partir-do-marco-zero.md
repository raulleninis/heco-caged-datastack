# F16 · Estoque a partir do marco zero

| | |
|---|---|
| **Esforço** | L (1 a 3 dias) |
| **Fase** | produção |
| **Depende de** | [F12](F12-for-exc-reconciliacao.md), [F09](F09-testes-de-qualidade.md) (staging materializada) |
| **Decisões associadas** | [D11](../decisoes/D11-estoque-de-emprego.md), [D06](../decisoes/D06-retencao-de-dados-brutos.md), [D03](../decisoes/D03-onde-guardar-os-dados.md) |

## Objetivo

Produzir o **estoque de emprego** por município × grupamento e, com ele, a taxa de
variação, a partir de um marco zero manual (estoque do painel do MTE ao **fim de
mar/2020**, ver [D11](../decisoes/D11-estoque-de-emprego.md)) e das movimentações
`MOV + FOR − EXC` a partir de **abr/2020**. Funciona hoje **só com Socorro** e aceita
outros territórios depois, **apenas inserindo dados**.

**Estado (28/09/2026):**

- **Parte 1 feita:** marco zero, `ajuste_marco_zero`, `mart_estoque` e testes. O estoque de
  Socorro bate com o painel em 84 de 84 valores (14 competências de 202006 a 202607).
- **Parte 2 feita (28/09/2026):** staging com Sergipe inteiro, seed `territorios.csv`, marts
  do boletim filtrando o município, SHA-256 no registro de ingestão. Histórico reprocessado
  (`backfill 2020..2026 --refazer`, 1 h 28 min): 1,49 milhão de linhas de MOV dos 75 municípios,
  233 arquivos com SHA-256, e Socorro idêntico ao de antes grupo a grupo. Warehouse: 50,5 MiB.
  Memória com limite de 830 MiB: pico de 405 MiB por arquivo MOV e 398 MiB nos marts (todos os
  territórios ativos).
  **Ativos:** Socorro, Aracaju, Barra dos Coqueiros, São Cristóvão e Sergipe (UF), todos
  conferidos com o painel (84/84 cada). O "Não Identificado" de Sergipe é negativo no próprio
  painel: esse grupamento tem teste de estoque negativo em `warn`; os outros cinco, em `error`.
- **Parte 3 (item 6, boletim):** não começada.

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

✅ Seed [`dbt/seeds/territorios.csv`](../../dbt/seeds/territorios.csv): `territorio`
(código de 6 dígitos, o que aparece nos arquivos, ou `28` para a UF), `nome`, `tipo`
(`municipio` ou `uf`), `ativo`. Já traz os cinco territórios do marco zero; só Socorro
ativo até o histórico ser reprocessado. O macro `efeito_no_saldo()` faz o join: `municipio`
casa com o município, `uf` com a UF inteira.

Os marts de fluxo e salário (`mart_caged_mensal_grupamento`, `mart_caged_reconciliado`) e o
boletim continuam sendo de **um município**: filtram `municipio = var('municipio_boletim')`
(280480, em `dbt_project.yml`).

### 2. Marco zero

**Já coletado** (28/09/2026): um CSV por território em
[marco-zero/estoque/](../../marco-zero/estoque/), versionado no git, com fonte e
conferência em [marco-zero/FONTE.md](../../marco-zero/FONTE.md). Territórios: Socorro,
Aracaju, Barra dos Coqueiros, São Cristóvão e Sergipe. O dbt lê os arquivos por glob
(source `marco_zero.estoque`, pasta montada em `/marco-zero:ro` no container) e os
materializa em `stg_marco_zero_estoque` ✅. Adicionar um território = adicionar um
arquivo; `marco-zero/normalizar.py` gera os CSVs a partir dos originais do painel.

| coluna | |
|---|---|
| `territorio` | código de 6 dígitos (UF: `28`) |
| `grupamento` | mesmas seis categorias do código, incluindo "Não Identificado" |
| `estoque` | valor do painel |
| `data_referencia` | `2020-03-31` |
| `retificacoes_ate` | último arquivo FOR/EXC que o painel já incorporava na coleta (`202607`) |
| `fonte` | **obrigatória**: de onde veio o número e a metodologia |
| `coletado_em` | data em que foi obtido |

O valor **nunca é editado** para absorver retificadores; isso é calculado (item 4).

### 3. Persistir as movimentações, por arquivo

✅ **Sem tabela nova.** As três stagings incrementais da F12 já são a persistência por
arquivo: `delete+insert` por `competencia_arquivo` (FOR/EXC) ou `competencia_mov` (MOV), então
reprocessar um arquivo **substitui** as linhas dele. Mudou só o filtro: de `município =
280480` para `uf = 28` (~26 mil linhas/mês no MOV, 74 municípios em 202607).

O registro `ingestao_arquivos` ganhou `sha256` e `bytes` do .7z baixado (NULL nos
registros anteriores), para identificar um arquivo histórico republicado pelo PDET, como
recomendou a [auditoria](../auditorias/2026-09-28-painel-vs-mart-socorro.md). Comparar com
o FTP periodicamente fica para depois.

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

Linhas de FOR/EXC com `competencia_mov <= 2020-03` **e** `competencia_arquivo > retificacoes_ate`
(202607) alimentam uma tabela derivada `ajuste_marco_zero` (por território × grupamento). O corte
em 202607 é a última competência que o painel já incorporava na coleta. As linhas
anteriores **já estão no marco zero**: em Socorro são 300 linhas com efeito −106, que
seriam contadas duas vezes. Hoje a tabela sai vazia.

Linhas com `competencia_mov` entre 2020-01 e 2020-03 **não** entram no acumulado do
estoque (continuam no fluxo).

✅ Feito: a regra do efeito vive num só lugar, o macro `efeito_no_saldo()`
([macros/estoque.sql](../../dbt/macros/estoque.sql)), usado por `ajuste_marco_zero`,
`mart_estoque` e pelos testes. Hoje `territorio` = código do município da staging; na
parte 2 passa a vir de `territorios.csv`.

### 5. Mart de estoque

✅ `mart_estoque`, uma linha por `(territorio, grupamento, competencia_mov)`, de 202001 à
última competência carregada:

- `saldo_consolidado` do mês (com o efeito acima; bate com `mart_caged_reconciliado`);
- `estoque = marco_zero + ajuste + acumulado do saldo após o marco`. **`NULL` antes da
  competência do marco e se não houver marco zero**; na competência do marco, é o próprio
  marco;
- `taxa_variacao_mensal = saldo ÷ estoque do mês anterior` (fração), `NULL` sem estoque
  anterior ou com estoque 0 (caso de "Não Identificado");
- `competencia_marco_zero`.

Território ativo = o que tem movimentação na staging. Um marco zero sem movimentação
(Aracaju hoje) é ignorado, para não virar um estoque parado.

**Sem marco zero para um território, nada quebra:** ele mantém fluxo, e estoque e taxa
ficam `NULL`.

### 6. Boletim

Os campos de estoque e taxa **só aparecem quando existem**, com a nota "estimativa a
partir de marco zero". Um território sem marco zero **não impede a geração** do boletim
nem o envio da [F15](F15-entrega-por-email-e-arquivo.md).

### 7. Testes

| teste | severidade | estado |
|---|---|---|
| **Continuidade:** existe `CAGEDMOV` para cada competência desde 202004, sem lacuna | `error` | ✅ `test_continuidade_mov` (já existia; confere desde 202001) |
| **Sinal da EXC:** admissões excluídas têm efeito `−1`; desligamentos excluídos, `+1` | `error` | ✅ `test_exc_preserva_sinal_do_evento` (já existia) + teste unitário `exclusao_de_admissao_reduz_estoque` |
| Estoque nunca negativo (cinco grupamentos principais) | `error` | ✅ `test_estoque_nao_negativo` |
| Estoque de "Não Identificado" negativo (é negativo no próprio painel para Sergipe) | `warn` | ✅ `test_estoque_nao_identificado_negativo` |
| `ajuste_marco_zero` não vazio (FOR/EXC de competência ≤ 202003 publicado depois de 202607) | `warn` (informa que o ajuste do marco zero foi acionado) | ✅ `test_ajuste_marco_zero_acionado` + teste unitário `ajuste_ignora_o_que_o_painel_ja_incorporou` |
| Marco zero: seis grupamentos por território, mesma `data_referencia` e mesmo `retificacoes_ate` | `error` | ✅ `test_marco_zero_completo` |
| Território ativo sem marco zero | `warn` | ✅ `test_territorio_sem_marco_zero` (lê o seed) |
| Unicidade do grão de `mart_estoque` | `error` | ✅ `test_unicidade_grao_estoque` |
| Território por município e por UF; inativo fora; ativo sem marco com estoque NULL | `error` | ✅ teste unitário `territorios_por_municipio_e_por_uf` |
| Coerência: saldo = reconciliado; estoque(t) − estoque(t−1) = saldo(t) | `error` | ✅ `test_coerencia_estoque` |
| **Estoque confere com o painel** (`marco-zero/validacao/`), recalculado só com os arquivos até a foto do painel, territórios ativos | `warn` | ✅ `test_estoque_confere_painel`: 84/84 por território em 28/09/2026 |
| Unicidade de (tipo, competência) no registro de ingestão | `error` | ✅ `test_unicidade_ingestao_arquivos` |

## Fora de escopo

- Estoque por sexo, raça/cor, ocupação ou faixa etária (decidido em
  [D11](../decisoes/D11-estoque-de-emprego.md): essas desagregações usam só fluxo).
- Obter os valores do marco zero.
- O painel autenticado e o envio ([F15](F15-entrega-por-email-e-arquivo.md)).

## Critério de aceite

1. ✅ Com **só Socorro**, `mart_estoque` traz estoque e taxa para cada grupamento.
2. ✅ **Ativar Aracaju** = mudar `ativo` em `territorios.csv`; Aracaju, Barra dos Coqueiros
   e São Cristóvão foram ativados assim, depois do reprocessamento único com `uf = 28`.
3. Parcial · Território **sem marco zero**: fluxo presente e estoque `NULL` (teste
   unitário `territorios_por_municipio_e_por_uf`); falta "boletim gerado" (parte 3).
4. Não testado diretamente · **Reprocessar o mesmo arquivo duas vezes** não altera o
   estoque. Depende do incremental `delete+insert` das stagings (F12), que já existia; o
   `mart_estoque` é recalculado inteiro a cada run.
5. Não testado diretamente · **Apagar o `.duckdb` e reconstruir** dá o mesmo estoque: o
   marco zero vem do git e é relido a cada run, mas reconstruir exige baixar o histórico.
6. ✅ **Fixture de exclusão:** uma exclusão de admissão reduz o estoque em 1 (teste
   unitário `exclusao_de_admissao_reduz_estoque`).
7. ✅ Comparar o **saldo mensal consolidado** e o **estoque** com o painel oficial do MTE:
   saldo coincide em 70 de 72 meses de 2020–2025 (as exceções são 202001 e 202003,
   [auditoria](../auditorias/2026-09-28-painel-vs-mart-socorro.md)); estoque coincide em
   84 de 84 valores (14 competências de 202006 a 202607) em cada um dos cinco territórios.
