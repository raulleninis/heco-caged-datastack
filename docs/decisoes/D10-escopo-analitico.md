# D10 · Escopo analítico do projeto

**Status:** decidida (21/09/2026) · **Bloqueia:** [F10](../fatias/F10-camada-analitica.md) · **Urgência:** alta

## Contexto

Esta é a decisão mais importante para o objetivo de **currículo**, e a única desta
lista que não nasceu de um defeito técnico.

A staging carrega **28 colunas**: `sexo`, `raca_cor`, `idade`, `grau_de_instrucao`,
`cbo_2002_ocupacao`, `tam_estab_jan`, `horas_contratuais`, `tipo_movimentacao`…

O mart usa **duas**: `competencia_mov` e `grupamento`.

O dado mais interessante do projeto **já está ingerido e parado**.

## A pergunta que o projeto responde hoje

*"Qual o saldo de emprego por setor em N. Sra. do Socorro, mês a mês?"*

É uma pergunta legítima — mas é a pergunta que o **painel oficial do PDET já responde**,
de graça, com mais recursos. Um avaliador pode perguntar: *por que este projeto existe?*

## Opções de escopo

### A. Manter o escopo atual e polir
| ✅ | Barato; foco em qualidade de engenharia |
| ❌ | Não diferencia — replica um painel público |

### B. Aprofundar a análise demográfica e ocupacional ✅ recomendada
Quem está sendo admitido e demitido: por sexo, raça/cor, faixa etária, escolaridade;
quais ocupações crescem e quais somem; como o salário de admissão difere entre grupos.

| ✅ | Usa dado já ingerido — custo marginal baixo |
| ✅ | É análise **de verdade**, não agregação |
| ✅ | Demonstra exatamente o que vaga de analista pede |
| ✅ | Gera achados que o painel oficial não entrega mastigados |
| ⚠️ | Exige cuidado interpretativo (correlação ≠ causa; amostra pequena por recorte) |

### C. Comparação territorial
N. Sra. do Socorro **contra** Aracaju, contra a média de SE, contra municípios de porte
similar. Dá escala ao número: −42 é muito ou pouco?

| ✅ | Transforma número solto em **contexto** — a competência central de um analista |
| ✅ | O filtro já existe; é relaxar o `WHERE`, não reescrever |
| ⚠️ | Aumenta o volume processado (hoje o filtro é agressivo de propósito) |

### D. Pergunta de negócio específica
Escolher **uma** pergunta e respondê-la bem. Ex.: *"a indústria de N. Sra. do Socorro
está perdendo espaço para serviços?"* — os dados de 202601–202605 já sugerem movimento.

| ✅ | Narrativa forte: projeto com tese, não com dashboard |
| ✅ | Excelente material de entrevista |
| ⚠️ | Exige conhecimento do contexto local (que você tem, e é uma vantagem real) |

## Recomendação

**B + C, ancoradas por D.**

Escolha uma pergunta que importe para o município (D), responda com recorte
demográfico e ocupacional (B), e dê escala comparando com Aracaju ou SE (C).

Essa combinação muda a frase de apresentação do projeto de:

> *"Fiz um pipeline que ingere o CAGED."* ← engenheiro júnior

para:

> *"Descobri que o saldo de emprego em N. Sra. do Socorro é sustentado por serviços de
> baixa remuneração enquanto a indústria encolhe — e construí o pipeline que apura isso
> todo mês, automaticamente."* ← analista que entende o negócio

A segunda frase contém a primeira. A primeira não contém a segunda.

## Nota sobre o recorte geográfico

O recorte em um município é uma **força**, não uma limitação: "mercado de trabalho de
Nossa Senhora do Socorro" é muito mais memorável que "análise do CAGED". Mantenha o
foco; use a comparação (C) só como régua.

## Decisão

> **Data:** 21/09/2026
> **Escolha:** **B + C, ancoradas por D.**
> **Porquê:** dá ao projeto uma tese em vez de um painel, e usa dado já ingerido. O
> boletim mensal da [F15](../fatias/F15-entrega-por-email-e-arquivo.md) é o veículo
> natural dessa análise.

**Ainda em aberto:** **qual é a pergunta de negócio (D)**. A decisão fixa o método, mas a
pergunta específica precisa ser escolhida ao começar a [F10](../fatias/F10-camada-analitica.md).

**Restrição incorporada em 22/09/2026 ([D11](D11-estoque-de-emprego.md)):** o estoque
existe só por município × grupamento, a partir de um marco zero manual. Logo, a parte B
(recortes demográficos e ocupacionais) usa **fluxo**: um mês, últimos 12 meses, mesmo
mês do ano anterior, composição das admissões e desligamentos. **Não há taxa por sexo,
raça/cor ou ocupação.** A parte C (comparação territorial) por taxa só vale onde houver
marco zero; sem ele, compara-se fluxo.

**Insumo novo (22/09/2026):** a staging agora expõe `subgrupamento`, o nível 2 da
Tabela 1 do MTE (abre Indústria em "Indústrias de Transformação" vs. o resto, e
Serviços em 6 subcategorias oficiais — transporte; alojamento e alimentação;
informação/financeiro/imobiliário/profissional/administrativo; administração
pública/educação/saúde; outros serviços; serviços domésticos). É o recorte fino que a
parte B pode usar sem inventar categoria: nos dados de Socorro (jan–mai/2026), o
subgrupamento que junta J,K,L,M,N concentra **saldo −447 de um total de Serviços
próximo de −164** — é ele que sustenta a tese de "serviços perdendo espaço", não o
grupamento Serviços como um todo.

**Custo a vigiar:** a comparação territorial (C) relaxa o filtro do município, e hoje esse
filtro é agressivo de propósito. Numa VM de 830 MiB dividida com outra aplicação
([D02](D02-modelo-de-execucao.md)), isso precisa ser **medido**. Comparar com Aracaju e
com Sergipe é bem menos dado que o Brasil inteiro.
