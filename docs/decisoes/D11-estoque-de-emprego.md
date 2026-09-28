# D11 · Como constituir o estoque de emprego

**Status:** decidida, revisada em 22/09/2026, com pontos abertos · **Bloqueia:** [F16](../fatias/F16-estoque-a-partir-do-marco-zero.md), [F10](../fatias/F10-camada-analitica.md) (indicadores de taxa) · **Urgência:** média

## Contexto

O MTE migrou o CAGED para o sistema novo (eSocial), e nele **só há dados a partir de
janeiro de 2020**. Movimentações dão o **fluxo**; o **estoque** (quantos vínculos
existem) é um nível, e um nível não se reconstrói somando fluxos sem um ponto de partida.

Estado hoje: o mart tem `saldo_liquido` por mês e grupamento
([mart_caged_mensal_grupamento.sql](../../dbt/models/marts/mart_caged_mensal_grupamento.sql)),
mas **nenhuma noção de nível**. Sem estoque não há taxa (`saldo ÷ estoque`), e a taxa é
o que permite comparar territórios de tamanhos diferentes (parte C da
[D10](D10-escopo-analitico.md)).

## Histórico

| Data | Decisão |
|---|---|
| 21/09/2026 | valor inicial manual **em jan/2020, já após as movimentações do mês**; fonte a definir (RAIS considerada) |
| 22/09/2026 | **RAIS descartada** (exigiria mais tempo que o disponível). Valor inicial manual = **marco zero anterior a jan/2020**; movimentações aplicadas por cima desde jan/2020 |
| **28/09/2026** | Marco zero passa a ser o **estoque do painel do MTE ao fim de mar/2020**; movimentações aplicadas desde **abr/2020**. Motivo: 202001 e 202003 divergem do painel por versão dos `CAGEDMOV` no FTP, não por erro do projeto |

## Decisão vigente (28/09/2026)

> **Escolha:** usar como **marco zero** o estoque do **painel do Novo CAGED (MTE)** ao
> **fim de março de 2020**, **por território × grupamento**. O estoque de cada mês sai
> das movimentações aplicadas a partir de **abr/2020**. Valores e fonte em
> [marco-zero/](../../marco-zero/FONTE.md).
> **Porquê:** o painel é a fonte oficial do nível e já traz as retificações. Ancorar em
> mar/2020 deixa fora da série os dois meses em que os microdados do FTP não reproduzem
> o painel (202001 e 202003).

```
estoque(t) = marco_zero_ajustado + Σ efeito_no_saldo, de abr/2020 até t

efeito_no_saldo:   CAGEDMOV → +saldo_movimentacao
                   CAGEDFOR → +saldo_movimentacao
                   CAGEDEXC → −saldo_movimentacao      (ver "Sinal das exclusões")

marco_zero_ajustado = marco_zero_manual + Σ efeito_no_saldo das linhas de FOR/EXC
                      com competência de movimentação ATÉ mar/2020
                      E vindas de arquivos POSTERIORES a 202607
```

O corte em 202607 existe porque o painel (atualizado em 28/08/2026) **já inclui** os
retificadores publicados até essa competência. Em Socorro são 300 linhas (efeito −106)
que, somadas de novo, contariam duas vezes.

Regras que valem junto:

1. **O valor manual é imutável.** O ajuste é **calculado** numa tabela derivada, nunca
   digitado por cima. Reconstruir o warehouse do zero reproduz o mesmo resultado.
2. **Territórios:** marco zero coletado para Nossa Senhora do Socorro (**280480**; códigos
   de 6 dígitos, os que aparecem nos arquivos), Aracaju (280030), Barra dos Coqueiros
   (280060), São Cristóvão (280670) e Sergipe (UF 28). Cada um passa a ter estoque quando
   for ativado, **sem reprocessar o histórico**.
3. **A falta de marco zero de um território não bloqueia nada.** Estoque e taxa ficam
   `NULL` para ele; fluxo e boletim continuam sendo gerados.
4. **Desagregações (sexo, raça/cor, faixa etária, ocupação) usam só fluxo**: um mês, uma
   janela (últimos 12 meses), comparação com o mesmo mês do ano anterior, participação
   na composição. Não há estoque nesses recortes.

### O que muda

| | Antes (código hoje) | Depois |
|---|---|---|
| Mart | só fluxo | fluxo **e** nível, e taxa derivada |
| Insumos | tudo vem do FTP e é regenerável | **um insumo manual**, o marco zero |
| Arquivos ingeridos | só `CAGEDMOV` | `CAGEDMOV` + `CAGEDFOR` + `CAGEDEXC` |
| Séries | independentes mês a mês | **cumulativas** |
| Filtro territorial | `município = 280480` fixo na staging | persiste `uf = 28`; o município vira configuração |

*Nada foi aplicado ao código.* A implementação é a [F16](../fatias/F16-estoque-a-partir-do-marco-zero.md).

## Sinal das exclusões

Segundo a definição que você trouxe, a exclusão de uma admissão **reduz** o saldo e a de
um desligamento o **eleva**: o efeito é o **inverso** do evento excluído.

**Conferi nos dados** (`CAGEDEXC202607`): a coluna `saldomovimentacao` do arquivo de
exclusões **preserva o sinal do evento excluído** (tipos de admissão com `+1`, de
desligamento com `−1`). Ela **não** vem já invertida. Logo, somar o saldo do EXC como
está daria o sinal errado: o efeito é `−saldo`. Vale um teste que trave isso.

## O que verifiquei no FTP (22/09/2026, dois meses)

Amostra: `CAGEDFOR` e `CAGEDEXC` de 202606 e 202607.

| Achado | Evidência |
|---|---|
| **FOR é incremental** | todas as linhas do arquivo de 202606 têm `competenciadec = 202606`; **0 linhas idênticas** entre 202606 e 202607 |
| **EXC é incremental** | **0 linhas idênticas** entre 202606 e 202607 |
| **FOR retroage ~12 meses** | menor `competenciamov` de 202606 é 202506; o de 202607 é 202507 |
| **EXC retroage até jan/2020** | menor `competenciamov` é 202001 nos dois; 81 e 252 linhas de 2020 |
| **Nada anterior a 2020 nessas amostras** | 0 linhas com `competenciamov < 202001` nos quatro arquivos |
| **Colunas** | FOR tem as 28 do MOV; EXC tem 30 (mais `competenciaexc` e `indicadordeexclusao`) |
| **Tamanho** | FOR e EXC são pequenos (< 1 MB compactados); MOV, ~55 MB |

Por serem incrementais, o risco de contar o mesmo evento em dois arquivos não aparece, e
o estoque pode ser recalculado somando tudo que existe. **Só dois meses foram
amostrados**: isto não prova que nunca haverá competência anterior a 2020 nos
retificadores. Por isso a regra do ajuste do marco zero continua valendo.

## O que as desagregações passam a permitir

| Pergunta | Suportada? |
|---|---|
| Saldo por sexo, raça/cor, ocupação, idade em um mês ou em 12 meses | sim (fluxo) |
| Comparação com o mesmo mês do ano anterior | sim |
| Composição: "mulheres foram X% das admissões" | sim |
| **Taxa** de rotatividade ou crescimento **por sexo/raça/ocupação** | **não** (não há estoque nesse recorte) |
| Taxa por município × grupamento | sim, onde houver marco zero |

## Consequências

| # | Ponto | O que fazer |
|---|---|---|
| 1 | **O nível absoluto não tem validação.** Sem fonte oficial para conferir, a qualidade do estoque é a do marco zero. Um erro na base distorce toda taxa na mesma proporção. | Rotular o estoque como **estimativa**. As variações (saldo) continuam confiáveis. |
| 2 | **O marco zero não se regenera.** | Versionar como *seed* do dbt no git, com **fonte, data de referência e data de coleta**. Único insumo que a [D03](D03-onde-guardar-os-dados.md) (sem backup) não recupera sozinho. |
| 3 | **A história é revisada.** Um retificador que chega hoje muda o estoque de meses passados. | O arquivo dos boletins enviados guarda o que foi enviado ([F15](../fatias/F15-entrega-por-email-e-arquivo.md)). |
| 4 | **O grupamento do marco zero tem que ser o mesmo do código:** A / B–E / F / G / H–U. | Documentar a regra no seed. O FTP tem um "Comunicado - Grupamento de Atividades Econômicas.pdf" na raiz; não o li. |
| 5 | **Erro cumulativo:** um mês faltante quebra a série. | Teste de continuidade desde abr/2020 ([F16](../fatias/F16-estoque-a-partir-do-marco-zero.md)). |
| 6 | **Sem raw, reprocessar exige guardar as movimentações.** | Persistir as linhas de Sergipe já filtradas ([F16](../fatias/F16-estoque-a-partir-do-marco-zero.md)); alinha-se à [D06](D06-retencao-de-dados-brutos.md) (B). |

## Pontos abertos

- ~~O valor e a fonte do marco zero de Socorro~~ e ~~os de Aracaju e Sergipe~~.
  **Resolvido em 28/09/2026:** painel do MTE, mar/2020, em [marco-zero/](../../marco-zero/FONTE.md).
- **Divergência de 202001 e 202003** entre o FTP e o painel
  ([auditoria](../auditorias/2026-09-28-painel-vs-mart-socorro.md)): pedir esclarecimento
  ao MTE/PDET. Afeta o fluxo desses meses, não o estoque.
- ~~Ler o "Comunicado - Grupamento de Atividades Econômicas" e conferir se o
  agrupamento do código combina com o oficial.~~ **Resolvido em 22/09/2026:** o
  `grupamento` do código já reproduzia a Tabela 1 do MTE letra a letra (A / B,C,D,E /
  F / G / H–U). Foi adicionado `subgrupamento`, o nível 2 dessa mesma tabela — ver
  [stg_caged_movimentacoes.sql](../../dbt/models/staging/stg_caged_movimentacoes.sql).
  O marco zero deve usar a granularidade que fizer sentido: por `grupamento` (6
  categorias) ou por `subgrupamento` (mais fino, mas exige mais valores manuais).
- **A pasta `Legado`** do FTP: não a abri. Pode conter o CAGED anterior a 2020, o que
  seria uma pista para a fonte do marco zero; o universo de vínculos pode não coincidir
  com o do eSocial.
- **Ampliar a amostra** dos retificadores para confirmar se aparece competência anterior
  a 2020.
