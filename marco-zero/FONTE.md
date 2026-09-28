# Fonte do marco zero do estoque (F16 / D11)

| item | valor |
|---|---|
| **De onde veio** | Painel do Novo CAGED do MTE (Power BI): <https://app.powerbi.com/view?r=eyJrIjoiNWI5NWI0ODEtYmZiYy00Mjg3LTkzNWUtY2UyYjIwMDE1YWI2IiwidCI6IjNlYzkyOTY5LTVhNTEtNGYxOC04YWM5LWVmOThmYmFmYTk3OCJ9> |
| **Indicador** | estoque de emprego formal ao **fim da competência 202003**, por grande grupamento (`Grande Grupamento` no painel = `grupamento` no projeto) |
| **Metodologia** | a do Novo CAGED, a mesma das movimentações que o projeto aplica por cima (`MOV + FOR − EXC`) |
| **Retificações incluídas** | as publicadas até a atualização do painel de **28/08/2026** (última competência: **202607**) |
| **Data de referência** | 2020-03-31 |
| **Quando foi obtido** | 28/09/2026 (março). A planilha de janeiro foi obtida em 22/09/2026 |
| **Redistribuição** | dado agregado e público; sem microdado individual |

## Territórios

| código | território | tipo | arquivo |
|---|---|---|---|
| 280480 | Nossa Senhora do Socorro | municipio | [estoque/280480_nossa_senhora_do_socorro.csv](estoque/280480_nossa_senhora_do_socorro.csv) |
| 280030 | Aracaju | municipio | [estoque/280030_aracaju.csv](estoque/280030_aracaju.csv) |
| 280060 | Barra dos Coqueiros | municipio | [estoque/280060_barra_dos_coqueiros.csv](estoque/280060_barra_dos_coqueiros.csv) |
| 280670 | São Cristóvão | municipio | [estoque/280670_sao_cristovao.csv](estoque/280670_sao_cristovao.csv) |
| 28 | Sergipe | uf | [estoque/28_sergipe.csv](estoque/28_sergipe.csv) |

Os códigos têm 6 dígitos (os que aparecem nos microdados); Sergipe usa o código da UF.

## Por que março de 2020, e não dezembro de 2019

Uma [auditoria](../docs/auditorias/2026-09-28-painel-vs-mart-socorro.md) (28/09/2026) comparou o mart com o painel de jan/2020 a dez/2025 para Socorro:
**só 202001 e 202003 divergem**. A causa provável é uma versão diferente desses dois `CAGEDMOV`
entre o FTP e a base do painel. Não há erro de carga nem da reconciliação. Ancorar o estoque no
painel em **mar/2020** e aplicar as movimentações só a partir de **abr/2020** deixa os dois meses
problemáticos fora da série de estoque.

## Originais

- [Caged Mar 2020.csv](Caged%20Mar%202020.csv): **fonte dos valores**. Uma linha `TOTAL` por
  território, usada só para conferência.
- [Caged Jan 2020.xlsx](Caged%20Jan%202020.xlsx): estoque de jan/2020. Não entra no cálculo;
  serve de prova cruzada.

## Normalização

- Nomes padronizados para os seis grupamentos do código: `Agropecuária`, `Indústria`,
  `Construção`, `Comércio`, `Serviços`, `Não Identificado`.
- Grupamento ausente no painel vale **0**. É o caso de "Não Identificado" em Socorro, Barra dos
  Coqueiros e São Cristóvão.
- Em todo território, a soma dos grupamentos é igual ao `TOTAL` do painel.
- São Cristóvão, Construção = 114. O valor é baixo, mas foi conferido no painel.

## Conferência feita

Para Socorro: **estoque de jan (painel) + saldo consolidado de fev (mart local) + saldo de mar
(painel) = estoque de mar (painel)**, em todos os grupamentos:

| grupamento | jan | fev (local) | mar (saldo) | = mar (estoque) |
|---|---:|---:|---:|---:|
| Agropecuária | 79 | +3 | 0 | 82 |
| Indústria | 6.372 | −48 | +34 | 6.358 |
| Construção | 1.177 | +12 | −13 | 1.176 |
| Comércio | 5.608 | −12 | −28 | 5.568 |
| Serviços | 8.778 | +60 | −21 | 8.817 |
| **Total** | **22.014** | **+15** | **−28** | **22.001** |

Isso confirma duas coisas: o "estoque" do painel é o do **fim** da competência, e o painel inclui
as mesmas retificações que o mart.

## Validação da série (28/09/2026)

O estoque calculado a partir deste marco (`mart_estoque`) foi comparado com o do painel em 14
competências, de 202006 a 202607 ([validacao/](validacao/), original em
`Caged Estoque 2020-2026 v2.csv`): **84 de 84 valores idênticos em cada um dos cinco
territórios**, Sergipe inclusive (conferido com a UF ativada numa cópia do warehouse). O
`test_estoque_confere_painel` repete a conferência a cada run, para os territórios ativos. Se um
dia divergir, a primeira competência com diferença indica onde procurar.

**"Não Identificado" em branco no painel:** o painel esconde esse grupamento quando ele é zero ou
negativo, mas o TOTAL o inclui. O `normalizar.py` o deriva como TOTAL − os outros cinco (e confere
quando vem preenchido).

## Inconsistência conhecida: "Não Identificado" de Sergipe

O painel dá **5** de estoque "Não Identificado" para Sergipe e **16** para Aracaju, que é parte
de Sergipe (o mesmo nas planilhas de jan e de mar/2020). A série da UF nesse grupamento fica
**negativa no próprio painel** (−4 em 202212, 202306 e 202506; −3 em 202607), e o mart a reproduz
exatamente. Enquanto `test_estoque_nao_negativo` for `error` para todo grupamento, Sergipe fica
**inativo** em `dbt/seeds/territorios.csv`. O valor não foi alterado: o marco é imutável.

## Regra de ajuste (atenção)

O estoque de mar/2020 já inclui as retificações de competências até 202003 publicadas até 202607.
Em Socorro, isso são 282 linhas FOR e 18 EXC, com efeito líquido de −106. **Somá-las de novo
contaria duas vezes.** O `ajuste_marco_zero` só pode usar linhas FOR/EXC com
`competencia_mov <= 202003` vindas de **arquivos posteriores a 202607**.

O valor manual é **imutável**: não se edita para absorver retificações.
