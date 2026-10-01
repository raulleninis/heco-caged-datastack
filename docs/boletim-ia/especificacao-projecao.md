# Especificação: projeção do emprego formal para o Boletim CAGED (seção "Perspectivas")

> Documento recebido do usuário em 01/10/2026 e guardado sem alterações de conteúdo. É o contrato
> da implementação em `pipeline/flows/projecao.py` ([F21](../fatias/F21-projecao-perspectivas.md)).
> As adaptações ao projeto (onde ficam as edições, gráfico vetorial no PDF, textos fora do prompt)
> estão na F21; método, parâmetros e textos são os daqui. A metodologia explicada fica no README,
> seção "Projeção do emprego (seção Perspectivas)".

> **Para a IA que vai implementar.** Este documento define, sem ambiguidade, como calcular a projeção de admissões, desligamentos e estoque de vínculos formais de Nossa Senhora do Socorro e como inseri-la no boletim mensal. Siga os passos na ordem. Não troque métodos, parâmetros ou textos sem instrução explícita. Existe uma implementação de referência em Python (`projecao_caged.py`). Se você gerar código novo, ele deve reproduzir os valores do **teste de aceitação** (seção 11).

---

## 1. Objetivo e frequência

- Toda edição mensal do boletim (competência `T`, o último mês com dados) ganha a seção **"05 Perspectivas"**, entre "04 Perfil e remuneração" e "Pontos de atenção".
- A seção mostra: um parágrafo, três indicadores, um gráfico, uma legenda e um parágrafo de revisão frente à edição anterior.
- A projeção vai até **dezembro do ano seguinte** ao ano de referência.
- **Ano de referência:** o ano de `T`. Na edição de dezembro (`T` = dezembro), passa a ser o ano seguinte.

## 2. Stack

Python ≥ 3.10, `pandas`, `numpy`, `statsmodels` ≥ 0.14 (`ExponentialSmoothing`), `duckdb`, `matplotlib`. Versões testadas: pandas 3.0, numpy 2.4, statsmodels 0.15, duckdb 1.5, matplotlib 3.10.

## 3. Entradas

| Entrada | Origem | Observação |
|---|---|---|
| Admissões e desligamentos mensais do município | `mart_caged_reconciliado` (DuckDB). Somar `admissoes_consolidadas` e `desligamentos_consolidados` de todos os grupamentos, por `competencia_mov` (formato `AAAAMM`) | Inclui meses `consolidado` e `provisório`. A série começa em 2020-01 (Novo CAGED) e **não pode ter meses faltando**: se faltar, pare com erro |
| Estoque âncora | O **mesmo número de estoque publicado na página 1 do boletim** para o mês `T` | Ex.: 25.364 em ago/2026 |
| Edições anteriores | Tabela `projecao_edicoes` na mesma base | Criada pelo próprio processo (seção 8) |

Notação: `A_t` = admissões, `D_t` = desligamentos, `saldo_t = A_t − D_t`, `S_t` = estoque no fim do mês `t`.

## 4. Passo 1: reconstruir o estoque histórico

A base não traz estoque, então ele é reconstruído de trás para frente:

```
S_T = estoque_âncora
S_{t-1} = S_t − saldo_t        (para t = T, T−1, ..., início da série)
```

## 5. Passo 2: métodos de projeção

Origem `T`, horizonte `H` = número de meses de `T+1` até dezembro do ano seguinte ao ano de referência (de 13 a 24). Cada método usa **somente dados até `T`**.

### 5.1 Método A: taxas sazonais

1. Taxas históricas: `ta_t = A_t / S_{t−1}` e `td_t = D_t / S_{t−1}`.
2. Exclua todos os meses de **2020** (pandemia).
3. Para cada mês futuro `d` (mês do calendário `m`): `ta*_m` = média de `ta` nos **3 últimos anos disponíveis** em que o mês `m` existe (≤ `T`, sem 2020). O mesmo vale para `td*_m`.
4. Recursão, partindo de `s = S_T`:
   ```
   Â_d = ta*_m · s
   D̂_d = td*_m · s
   s   = s + Â_d − D̂_d        # o estoque projetado alimenta o mês seguinte
   ```

### 5.2 Método B: ETS (Holt-Winters)

- Ajuste um modelo separado para `log(A)` e outro para `log(D)`, com dados de **2021-01 até `T`**.
- Especificação: `ExponentialSmoothing(y, trend="add", damped_trend=True, seasonal="add", seasonal_periods=12).fit(optimized=True)`.
- Projeção: `exp(forecast(H))`.

### 5.3 Combinação (projeção oficial)

```
Â_d = (Â_d^taxas + Â_d^ETS) / 2
D̂_d = (D̂_d^taxas + D̂_d^ETS) / 2
saldo_d = Â_d − D̂_d
Ŝ_d = S_T + Σ (saldo de T+1 até d)        # identidade contábil, sempre
```

**Nunca** projete saldo ou estoque diretamente. Eles saem sempre de admissões e desligamentos.

### 5.4 Referência (só para validação): sazonal ingênuo

`Â_d = A_{d−12}` e `D̂_d = D_{d−12}`. Para horizontes acima de 12 meses, repete o último ano observado. Não é publicado.

## 6. Passo 3: backtest e faixa provável

1. **Origens:** todos os meses de **2022-12** até `T−1`. A cada edição entra uma origem nova.
2. Em cada origem `o`, rode os métodos com dados ≤ `o` (inclusive o estoque reconstruído) para o mesmo `H`.
3. Para cada horizonte `k` em que o mês `o+k` já é conhecido, guarde o erro de estoque da combinação: `e_k = S_{o+k} − Ŝ_{o+k}`.
4. **Faixa por horizonte:** `lo_k = quantil 10%(e_k)` e `hi_k = quantil 90%(e_k)` (`numpy.quantile`, interpolação linear padrão), desde que haja **≥ 8 erros**.
5. Para horizontes com menos de 8 erros: use o último horizonte válido `k*` e escale, `(lo_k, hi_k) = (lo_k*, hi_k*) · √(k/k*)`.
6. **Monotonicidade:** a incerteza não pode diminuir com o horizonte. Para `k ≥ 2`: `lo_k = min(lo_k, lo_{k−1})` e `hi_k = max(hi_k, hi_{k−1})`.
7. **Faixa do estoque:** `[Ŝ_d + lo_k, Ŝ_d + hi_k]`.
8. **Faixa do saldo do ano:** a faixa do estoque de dezembro do ano de referência menos `S` de dezembro do ano anterior.
9. **Métricas (só controle interno):** MAE do saldo mensal (horizontes 1 a 12) e MAE do estoque 12 meses à frente, para taxas, ETS, combinação e ingênuo.

## 7. Saídas

### 7.1 Indicadores (exatamente estes três, nesta ordem)

| Rótulo no boletim | Cálculo | Linha secundária |
|---|---|---|
| `ESTOQUE PROJETADO · DEZ/{ano}` | `Ŝ` em dezembro do ano de referência | `faixa: {lo} a {hi}` |
| `SALDO PROJETADO EM {ano}` | `Ŝ_dez(ano) − S_dez(ano−1)`, ou seja, o observado no ano mais o projetado até dezembro | `faixa: {lo} a {hi}` (com sinal) |
| `ESTOQUE PROJETADO · DEZ/{ano+1}` | `Ŝ` em dezembro do ano seguinte | `faixa: {lo} a {hi}` |

**Formatação:** inteiros arredondados, separador de milhar com ponto (25.673). Saldos sempre com sinal, usando `+` e `−` (sinal de menos U+2212).

### 7.2 Parágrafo principal (modelo fixo)

> Com base no padrão histórico de admissões e desligamentos, o estoque de vínculos formais deve encerrar {ano} em torno de {Ŝ_dez}, com faixa provável entre {lo} e {hi}. O saldo projetado para o ano é de {saldo_ano com sinal} vínculos, {leitura}.

`{leitura}` depende da faixa do saldo do ano:
- se o limite inferior for maior que 0: "o que indica crescimento do estoque até o fim do ano";
- se o limite superior for menor que 0: "o que indica retração do estoque até o fim do ano";
- nos demais casos: "o que indica estabilidade em relação ao nível atual".

### 7.3 Parágrafo de revisão (modelo fixo)

> **Revisão.** Na edição anterior, a projeção para o estoque de {mês T por extenso} era de {proj_ant_T}; o resultado foi {S_T} ({diferença com sinal}). Com isso, a projeção para dezembro de {ano} passou de {proj_ant_dez} para {Ŝ_dez} ({diferença com sinal}).

### 7.4 Legenda do gráfico

> Estoque de vínculos formais, jan/{aa−1} a dez/{aa+1}. Faixa provável: intervalo em que o resultado real ficou em 8 de cada 10 testes com dados passados.

### 7.5 Acréscimo à nota metodológica

> Projeção experimental: média de dois métodos (taxas sazonais de admissão e desligamento sobre o estoque e suavização exponencial de Holt-Winters). A faixa provável corresponde aos percentis de 10% e 90% dos erros observados em testes com dados passados. Revista a cada edição.

### 7.6 Regras de linguagem (obrigatórias)

- Tom neutro e descritivo, igual ao resto do boletim.
- **Não** comparar com períodos de gestões anteriores, **não** citar anos específicos como "bons" ou "ruins" e **não** usar "recorde", "pior", "melhor desde".
- **Não** apresentar a projeção como meta nem como dado oficial. É sempre "projeção" e "faixa provável".
- **Não** acrescentar interpretações causais que não estejam nos dados.
- Use apenas os modelos de texto acima. Se precisar de outro texto, peça instrução humana.

## 8. Armazenamento das edições e revisão

Ao publicar, grave a projeção mensal da edição (substituindo, se a edição já existir):

```sql
create table if not exists projecao_edicoes (
  edicao varchar,            -- 'AAAA-MM' (= T)
  competencia_alvo varchar,  -- 'AAAA-MM'
  admissoes double, desligamentos double, saldo double,
  estoque double, estoque_lo double, estoque_hi double,
  gerado_em timestamp);
```

Para a revisão, leia a edição mais recente com `edicao < T`. Se não existir (primeira execução), **recalcule** a projeção com dados até `T−1` e marque `revisao.origem = "recalculada"`.

## 9. Gráfico

- **Tipo:** linha, um único eixo vertical (estoque de vínculos). **Nunca** use dois eixos.
- **Janela:** janeiro do ano anterior ao de referência até dezembro do ano seguinte.
- **Camadas, de baixo para cima:**
  1. faixa provável (área azul `#3a5fa8`, 16% de opacidade), partindo de `S_T`;
  2. projeção da edição anterior (cinza `#9aa3b5`, pontilhada, a partir de `T−1`);
  3. estoque observado (`#1a2747`, linha cheia);
  4. projeção central (`#3a5fa8`, tracejada, partindo de `S_T`).
- **Marcações:**
  - linha vertical pontilhada em `T` com o rótulo "projeção →";
  - ponto cheio em `S_T` com o valor;
  - círculos vazados em dez/{ano} e dez/{ano+1} com os valores.
- **Estilo:**
  - fundo do painel `#eef1f6`, grade horizontal `#d9dee7`, sem bordas;
  - eixo X com rótulos só em janeiro e julho (`jan/25`, `jul/25`);
  - números no formato pt-BR;
  - legenda em uma linha acima do gráfico: Estoque observado · Projeção central · Faixa provável · Projeção da edição anterior.
- **Saída:** PNG em 200 dpi ou SVG, cerca de 7,6 × 3,2 polegadas. Função de referência: `grafico_perspectivas()`.

## 10. Validações antes de publicar

Bloqueiam a publicação:
- meses faltando na série;
- `NaN`, admissões ou desligamentos negativos na projeção;
- identidade violada: `Ŝ_d − Ŝ_{d−1} ≠ saldo_d`;
- faixa que não contém a projeção central.

Geram aviso para revisão humana:
- MAE do estoque 12 meses à frente da combinação **maior** que o do sazonal ingênuo;
- o estoque âncora diferente do estoque publicado na página 1;
- revisão da projeção de dezembro maior que a largura da faixa (sinal de quebra, mudança de base ou erro de dados).

Revisão anual (não mensal): reavaliar parâmetros (3 anos de média, início do ETS, exclusão de 2020) uma vez por ano, com o backtest. Mudanças entram na nota metodológica.

## 11. Teste de aceitação

**Entrada:**
- base `caged.duckdb` com dados até 2026-07, mais o complemento de agosto/2026 (admissões 1.028 e desligamentos 1.107, vindos do boletim);
- estoque âncora 25.364;
- sem edições armazenadas.

**Valores esperados** (tolerância de ±2 por arredondamento numérico do ETS):

| Item | Valor |
|---|---|
| Origens no backtest | 44 |
| Estoque projetado dez/2026 | 25.673 (faixa 25.162 a 26.315) |
| Saldo projetado em 2026 | +42 (faixa −469 a +684) |
| Estoque projetado dez/2027 | 25.780 (faixa 24.485 a 26.640) |
| Projeção de set/2026 (adm. / desl. / saldo) | 1.012 / 909 / +103 |
| Revisão (recalculada) | ago: 25.612 projetado contra 25.364 realizado (−248); dez/2026: de 26.075 para 25.673 |
| MAE estoque 12m: combinação / ingênuo | 591 / 623 |

**Comando de referência:**
```bash
python projecao_caged.py caged.duckdb --estoque 25364 --complemento '{"2026-08":[1028,1107]}' --grafico perspectivas.png
```

Em produção, o mês `T` já estará na base: rode sem `--complemento` e com `--salvar`, para gravar a edição.
