# F21 · Projeção do emprego: seção Perspectivas do boletim com IA

| | |
|---|---|
| **Esforço** | L (1 a 3 dias) |
| **Fase** | produção |
| **Depende de** | [F19](F19-boletim-com-ia.md) (boletim com IA), [F20](F20-estoque-de-referencia-do-mte.md) (estoque da página 1) |
| **Contrato** | [especificação da projeção](../boletim-ia/especificacao-projecao.md) (do usuário, 01/10/2026) |
| **Metodologia explicada** | README, seção "Projeção do emprego (seção Perspectivas, F21)" |

## Objetivo

Cada edição do boletim com IA ganha a seção **05 Perspectivas**: projeção experimental de admissões,
desligamentos e estoque até dezembro do ano seguinte, com faixa provável por backtest e revisão
frente à edição anterior. O Pix passa a ser a seção 06 e os pontos de atenção, a 07 (a última). As
fragilidades conhecidas vão na nota metodológica.

## O que foi feito (01/10/2026)

| peça | o quê |
|---|---|
| `pipeline/flows/projecao.py` | Cálculo da especificação: as funções de método (taxas, ETS, ingênuo, combinação, backtest, reconstrução do estoque) são as da implementação de referência do usuário, sem mudança de método nem de parâmetro. Validações da seção 10: as que bloqueiam viram `ProjecaoBloqueada` (a seção sai do boletim e o motivo vai ao relatório de revisão); as que avisam vão ao relatório. Textos fixos da seção 7, mais o aviso experimental e as fragilidades. `anexar()` põe o bloco em `fatos["projecao"]` (ou `fatos["projecao_ausente"]`) |
| Âncora | o estoque da página 1 (`fatos["panorama"]["estoque"]`, do `mart_estoque` da F20). A série tem de terminar na competência do boletim |
| Edições publicadas | `/data/ia/projecoes/<território>.duckdb`, tabela `projecao_edicoes` com o schema da especificação. Fora do warehouse: o boletim com IA o lê só para leitura, e o flow diário é o único escritor. Grava-se ao **publicar** (`entrega_ia.py enviar`), não ao gerar: uma geração de teste não vira "edição anterior" |
| `boletim_ia.py` | calcula a projeção depois dos indicadores (`--sem-projecao` desliga); o bloco fica **fora do prompt** (textos fixos, o LLM não escreve sobre a projeção); `boletim.md` ganha a seção |
| PDF (`pdf_analitico.py`, `pdf_design.py`) | seção 05 na ordem da especificação: parágrafo, três indicadores, gráfico, legenda, **aviso em bordô negrito destacado** (pedido do usuário: experimental, leia com cautela, valores podem mudar pela realidade e por ajustes no método) e o parágrafo de revisão com "**Revisão.**" em negrito. Gráfico vetorial desenhado com o fpdf2, seguindo a seção 9 (cores, camadas, marcações, eixo X em jan e jul, legenda numa linha) |
| Nota metodológica | o acréscimo da seção 7.5 e um parágrafo de fragilidades conhecidas (série curta, backtest curto e faixa extrapolada nos horizontes longos, faixa de erros passados, nada fora do CAGED, retificações e revisões do estoque de referência, erro médio do teste contra a referência ingênua) |
| Dependências | `numpy 2.4.6`, `pandas 3.0.6`, `scipy 1.17.1`, `patsy 1.0.3`, `statsmodels 0.15.0` (as versões testadas na especificação). Imagem: 1,14 GB → 1,48 GB. Só o boletim com IA importa; o flow diário não |
| Testes | `tests/test_projecao.py` (identidade, faixa, edição de dezembro, mês faltando bloqueia, revisão recalculada e depois armazenada, textos, sem âncora) e o **teste de aceitação** da seção 11, que roda com `PROJECAO_ACEITACAO_DB`; testes do PDF, do prompt e do relatório de revisão |

## Teste de aceitação (seção 11)

Base de 28/09/2026 (`data/warehouse/caged.duckdb.bak-20260929`, dados até 202607) + agosto do boletim,
âncora 25.364, sem edições: todos os itens dentro de ±2.

| item | esperado | obtido |
|---|---|---|
| origens no backtest | 44 | 44 |
| estoque dez/2026 | 25.673 (25.162 a 26.315) | 25.674 (25.162 a 26.316) |
| saldo 2026 | +42 (−469 a +684) | +43 (−469 a +685) |
| estoque dez/2027 | 25.780 (24.485 a 26.640) | 25.781 (24.486 a 26.641) |
| set/2026 adm./desl./saldo | 1.012 / 909 / +103 | 1.012 / 909 / +103 |
| revisão (recalculada) | 25.612 → 25.364; dez: 26.075 → 25.673 | 25.612 → 25.364; dez: 26.075 → 25.674 |
| MAE estoque 12m comb./ingênuo | 591 / 623 | 590,7 / 623,2 |

Com o warehouse atual (agosto já carregado, com os retificadores de agosto), dez/2026 sai em 25.673
(25.164 a 26.315), saldo +46.

## O que difere da especificação, e por quê

- **Gráfico sem matplotlib.** A especificação pede PNG/SVG via matplotlib; o boletim é desenhado em
  vetor pelo fpdf2 (como os demais gráficos). Mesmas camadas, cores, marcações e eixos; sem imagem
  rasterizada, sem mais uma dependência pesada, com as mesmas fontes do resto do PDF.
- **Edições fora do warehouse** e **gravadas ao publicar** (acima).
- **Aviso experimental em destaque** após o gráfico: acrescentado a pedido do usuário. É o único texto
  além dos modelos da especificação, junto com o parágrafo de fragilidades da nota metodológica,
  também pedido.

## Pontos abertos

- **Revisão "recalculada" na primeira edição.** Sem edição publicada, o modelo de texto da seção 7.3
  diz "Na edição anterior, a projeção…", mas essa projeção nunca foi publicada (foi recalculada com
  dados até o mês anterior). O relatório de revisão avisa; o texto segue o modelo até haver instrução.
- Revisão anual dos parâmetros (3 anos, início do ETS, exclusão de 2020) com o backtest.
