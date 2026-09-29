# Roteiro do boletim mensal de emprego municipal com IA

**Base:** Novo CAGED
**Unidade de análise:** município-alvo
**Periodicidade:** mensal
**Modelo de produção:** cálculos por código, destaques selecionados por regras, redação assistida por IA e aprovação humana antes do envio
**Objetivo:** descrever a evolução do emprego formal no município e contextualizar os movimentos mais relevantes com evidências locais e externas.

> **Princípio central:** o município é a unidade de referência. Os recortes regionais e estaduais
> servem como contexto e comparação, não como substitutos de evidências sobre a economia local.

> **Regras do projeto que este roteiro segue:** números só por código, nunca calculados pela IA;
> análise setorial, com desagregação só quando relevante e nunca no nível de empresa
> ([D10](../decisoes/D10-escopo-analitico.md)); salário com mediana e média
> ([D05](../decisoes/D05-metrica-de-salario.md)); estoque a partir de marco zero
> ([D11](../decisoes/D11-estoque-de-emprego.md)).

## 1. Estrutura do boletim

O boletim deve ser curto e comparável entre edições: de preferência **3 a 4 páginas**, com gráficos
e indicadores fixos e uma interpretação econômica voltada aos destaques do mês.

### 1.0. Critérios editoriais (revisão do primeiro boletim, 29/09/2026)

Leitor: gestor público. Cada edição deixa claro, rápido, **o que aconteceu, onde se concentrou,
como se compara com períodos anteriores e o que acompanhar**.

- **Seções fixas:** síntese; panorama; setores; contexto regional; perfil e remuneração; pontos de
  atenção; nota metodológica. Não há seção de hipóteses (ver 1.5).
- **Dois níveis:** o texto interpreta; **tabelas e gráficos, gerados por código a partir dos
  fatos**, detalham. O LLM nunca monta tabela. O texto pode omitir o que está na tabela.
- **Critério para um número entrar no texto:** descrever a dimensão de um resultado,
  contextualizá-lo ou mostrar uma mudança relevante. Números de uso interno (contribuição
  percentual de cada setor para o saldo, participação de uma atividade nas movimentações em 12
  meses) servem para escolher destaques, não para o texto.
- **Síntese** em até 3 frases, sem repetição no panorama. **Panorama** na ordem: mês, mesmo mês
  do ano anterior (pelo nome: "julho de 2025"), acumulado no ano, 12 meses.
- **Setores:** o destaque em detalhe; os demais numa frase ("nos demais setores, saldo conjunto
  de..."). Números como o saldo conjunto dos demais setores ou do restante de um grupamento são
  **calculados por código** e entram nos fatos; o redator não os calcula.
- **Faixa histórica:** ao citar, dizer o critério (mínimo e máximo do mesmo mês nos anos
  anteriores disponíveis).
- **Uma única menção à provisoriedade**, na nota metodológica. Categorias sem identificação,
  bases pequenas e a base do salário também vão para a nota.
- **Convenções:** "perda de 83 vínculos" ou "saldo negativo de 83" no texto (sinal só em
  tabela); **percentuais com 2 casas decimais**; "vínculos" para tudo; títulos em caixa de
  frase; sem travessão; sem expressões de preenchimento ("vale ressaltar", "no tocante").

### 1.1. Panorama do emprego municipal (obrigatório)

**Indicadores**

- Saldo de empregos (admissões menos desligamentos).
- Total de admissões e desligamentos.
- Estoque de vínculos formais e sua variação percentual, com a metodologia de reconstituição
  identificada (marco zero do painel do MTE em mar/2020 mais movimentações).
- Resultado do mês comparado ao mesmo mês do ano anterior.
- Saldo acumulado no ano e nos últimos 12 meses.
- Evolução histórica do saldo e identificação de movimentos atípicos.
- Aviso de provisoriedade: os últimos ~12 meses ainda recebem declarações fora do prazo e serão
  revisados.

**Perguntas para a IA**

- O saldo decorreu principalmente de mais admissões, de menos desligamentos ou de ambos?
- O resultado está dentro do padrão histórico para o mês?
- O ritmo de expansão ou retração mudou em relação ao período comparável?

### 1.2. Desempenho setorial (obrigatório)

**Base: os cinco grandes grupamentos.** Agropecuária, indústria, construção, comércio e serviços:
saldo, variação do estoque e contribuição de cada um para o saldo municipal. Ao interpretar
participações, considere que o saldo total pode estar próximo de zero ou ser negativo.

**Desagregação: só quando relevante.** Dentro de um grupamento em destaque, desça um nível
(subgrupamento ou divisão CNAE) quando uma atividade concentrar a maior parte dele. Exemplo: se a
indústria de transformação automotiva for a maior parte da indústria da região, faz sentido falar
dela para explicar o movimento da indústria.

- A relevância estrutural de uma atividade vem do **perfil econômico** (seção 2), não do mês.
- Prefira o nível mais agregado que ainda explique o movimento: subgrupamento, depois divisão CNAE
  (2 dígitos). Subclasse só em caso excepcional.
- Nunca no nível de empresa. Nunca cruzar CNAE detalhada com porte do estabelecimento, porque
  num município isso pode apontar um estabelecimento só.
- Não aprofundar uma atividade só porque seu crescimento percentual é alto sobre uma base pequena.
- O estoque existe só por grupamento. Para atividades desagregadas, use fluxo (saldo, admissões,
  desligamentos) e, para o peso estrutural, o perfil econômico.

**Perguntas para a IA**

- O resultado está concentrado em um grupamento ou disseminado entre setores?
- Os grupamentos que mais empregam também lideraram a movimentação do mês?
- Há movimentos relevantes em atividades características do município?

### 1.3. Contexto regional e referências comparativas (sintético)

Esta seção contextualiza o município; não produz um ranking de municípios. Usa **os recortes
disponíveis** na instalação, configurados como territórios com estoque:

- **Município × região:** um agrupamento de municípios definido na configuração, como uma região
  metropolitana ou uma região imediata. É calculado por código como soma dos municípios que a
  compõem, cada um com seu próprio marco zero.
- **Município × UF:** taxa de variação do estoque do estado.
- **Município × Brasil:** só quando o recorte estiver disponível. Não é obrigatório.

**Formato:** um gráfico ou tabela pequena e um parágrafo. Priorizar **taxas**, não saldos
absolutos de economias de tamanhos diferentes, e mostrar os valores absolutos ao lado. Nunca somar
a UF com os seus municípios.

### 1.4. Perfil das contratações (obrigatório, mas enxuto)

**Indicadores**

- Admissões por sexo.
- Admissões por faixa etária.
- Salário de admissão: **mediana** como referência, com a **variação nominal** frente ao mesmo mês
  do ano anterior, dita como nominal (sem correção pela inflação). A média fica fora do texto, a
  menos que tenha finalidade analítica.
- Só as categorias **relevantes** são comentadas: saldo acima do limiar de destaque ou mudança de
  participação nas admissões acima do limiar em pontos percentuais (calculada por código).

Quando houver mudança relevante, investigar a atividade econômica responsável, respeitando as regras
de desagregação da seção 1.2. Interpretar diferenças salariais com cautela, porque o perfil dos
contratados muda entre os meses. **Regra de base pequena:** recortes com poucas admissões são
sinalizados e não interpretados.

### 1.5. Interpretação da conjuntura (direcionada)

> **Decisão de 29/09/2026:** **sem hipóteses** enquanto não houver evidência externa (notícias,
> indicadores oficiais) que as sustente. Até lá, o boletim termina em **pontos de atenção**:
> indicadores a acompanhar nos próximos meses, sem especular causas. Com evidência, uma hipótese
> entra dentro dos pontos de atenção, nunca numa seção própria, com fonte e data, e só se a
> evidência a sustentar (julgamento na parte 3b-2).

Investigar **no máximo três fatores** com potencial para explicar os movimentos selecionados. Não é
necessário abordar todas as dimensões em todas as edições.

| Dimensão | O que verificar | Quando acionar |
|---|---|---|
| Sazonalidade local | Safras, entressafras, calendário comercial, férias, turismo, início ou fim de contratos | Sempre que o resultado diferir do mês anterior ou seguir padrão conhecido |
| Atividade produtiva local ou regional | Produção, vendas, serviços, demanda por insumos e vínculos entre setores | Quando houver variação setorial relevante |
| Acontecimentos locais | Obras, investimentos, abertura, expansão, paralisação ou fechamento de atividades, **conforme noticiado pela fonte** | Quando houver fonte pública e relação temporal plausível |
| Acontecimentos externos | Fatos fora do município com potencial de afetá-lo (ex.: política de uma cadeia produtiva, evento regional, decisão estadual ou nacional) | Quando houver fonte pública e ligação plausível com a estrutura produtiva local |
| Condições econômicas externas | Juros, crédito, câmbio, exportações, preços e custos | Somente se forem materialmente relevantes para a estrutura produtiva municipal |

**Como usar acontecimentos:**

- O fato vem da fonte, citada com data e link, e é descrito como ela o descreve.
- O texto **não afirma** que o movimento do CAGED é daquele estabelecimento ou evento: apresenta os
  dois lado a lado e rotula a ligação como hipótese.
- Números sobre um acontecimento, como "200 contratações anunciadas", só entram se estiverem na
  própria fonte.

**Regra de redação:** diferenciar resultado observado, evidência complementar e hipótese
explicativa. Não atribuir causalidade apenas porque duas variáveis se moveram no mesmo período.

---

## 2. Perfil econômico permanente do município

Preparado **uma vez na implantação** e revisado periodicamente. Orienta quais dados externos e quais
explicações a IA deve priorizar a cada mês. Fica num arquivo versionado da instância, com fonte e
data em cada campo.

**Campos essenciais**

- Município-alvo e recortes comparativos adotados (região e UF).
- Principais grupamentos por participação no estoque e, dentro deles, as atividades dominantes
  (subgrupamento ou divisão CNAE). Como não há estoque por atividade, o peso de uma atividade
  dentro do grupamento é a sua participação nas movimentações (admissões + desligamentos) dos
  últimos 12 meses, sempre identificado como aproximação. É daqui que vem a relevância para
  desagregar (seção 1.2).
- Cadeias produtivas e atividades de maior relevância econômica.
- Padrões sazonais de admissões, desligamentos e saldo, **calculados por código** a partir da série
  do CAGED.
- Relações econômicas com municípios vizinhos, a região e polos de emprego.
- Empreendimentos e investimentos relevantes, **conforme fontes públicas**. Não inclui lista de
  estabelecimentos inferida dos dados.
- Indicadores externos disponíveis para as atividades dominantes, com a escala de cada um
  (municipal, estadual, nacional).
- **Limiares de destaque** calibrados ao porte do município (seção 3).
- Fontes, período de referência e data da última atualização de cada informação.

**Atualização sugerida:** revisão anual, recalculando por código os campos que vêm do CAGED, e
atualização extraordinária quando houver mudança produtiva relevante e documentada.

---

## 3. Regras para seleção automática de destaques

A seleção é feita por código, com os limiares do perfil econômico. A IA recebe os resultados já
calculados.

1. **Peso econômico:** destacar os grupamentos que mais contribuem para o saldo ou que têm parcela
   importante do estoque; desagregar só nos casos da seção 1.2.
2. **Desvio sazonal:** comparar com o mesmo mês dos anos anteriores. Com a série desde 2020 há
   poucas observações por mês, então a regra inicial é "fora da faixa mínimo–máximo do mesmo mês
   desde 2020", e não desvio-padrão.
3. **Movimentação:** decompor a variação do saldo em admissões e desligamentos.
4. **Concentração:** sinalizar resultados fortemente concentrados em poucas atividades.
5. **Base pequena:** exigir um mínimo absoluto de vínculos para destacar uma atividade ou um
   recorte do perfil; sinalizar variações percentuais expressivas sobre estoque reduzido.
6. **Contexto:** usar o perfil econômico para decidir quais indicadores e acontecimentos consultar.

Os limiares são calibrados ao porte do município e à volatilidade da série, e ficam registrados no
perfil. Na ausência de desvio relevante, apresentar a evolução normal do período, sem criar
explicações extraordinárias.

### Exemplos de acionamento

| Sinal detectado no CAGED municipal | Investigação complementar |
|---|---|
| Queda de vínculos na agropecuária | Calendário de safra, condições climáticas e atividade agroindustrial local |
| Redução do emprego industrial | Atividade dominante da indústria local (perfil), produção da cadeia, acontecimentos noticiados |
| Aceleração do comércio | Sazonalidade, datas comerciais e vendas do varejo disponíveis para a região |
| Avanço da construção | Obras, empreendimentos, financiamento e investimentos noticiados |
| Expansão de alojamento e alimentação | Fluxo turístico, calendário de eventos e sazonalidade local |
| Saldo fortemente negativo em um grupamento | Separar aumento dos desligamentos de queda das admissões; desagregar se a seção 1.2 permitir; verificar acontecimentos noticiados |

---

## 4. Dados e fontes

| Conjunto | Uso | Atualização |
|---|---|---|
| Novo CAGED municipal | Movimentações, saldos, estoque reconstituído e características dos vínculos | Mensal; registrar extração e ajustes |
| Histórico municipal consolidado | Sazonalidade, tendência e comparações interanuais | A cada divulgação |
| Painel do MTE (coletor) | Marco zero do estoque e conferência da série | Na implantação e ao adicionar território |
| Banco Central: Pix por município | Aproximação da atividade das empresas LOCAIS (empresas recebedoras e valor recebido), sempre em leitura relativa (município × região × UF), porque o Pix ainda cresce por adoção; nominal; município do cadastro da conta | Mensal, publicado antes do CAGED |
| Banco Central: Selic | Contexto só quando Construção ou Comércio estão em destaque; nunca causa | Mensal |
| IBGE: API de notícias e releases | Evidência de escala estadual ou nacional (os demais dados do IBGE não descem a município ou saem com pouca frequência) | Conforme divulgação |
| Fontes públicas locais, regionais e nacionais | Acontecimentos locais e externos, conforme noticiados | Quando houver fato relevante |
| Comex Stat e fontes internacionais | Comércio exterior e preços, se a cadeia local justificar | Condicional |

**Defasagem e escala:** informar a competência e a escala de cada indicador. Um dado estadual ou
nacional, ou de outro período, não é apresentado como evidência direta da dinâmica municipal do
mesmo mês.

---

## 5. Fluxo mensal de automação

1. **Coletar:** importar a nova competência do CAGED, as revisões e os indicadores complementares
   disponíveis.
2. **Validar e calcular:** conferir abrangência territorial, classificações, totais, saldos,
   estoque, taxas e acumulados por código.
3. **Selecionar destaques:** aplicar as regras de relevância, sazonalidade, concentração e base
   pequena, com os limiares do perfil.
4. **Consultar o perfil municipal:** identificar atividades dominantes, sazonalidades e indicadores
   associados aos destaques.
5. **Investigar pontualmente:** recuperar apenas evidências e acontecimentos pertinentes, com fonte
   e data.
6. **Redigir com IA:** produzir texto curto, distinguindo fatos e associações; hipóteses só com evidência (1.5).
7. **Validar:** confrontar todos os números com as tabelas e verificar fontes, datas e linguagem
   causal.
8. **Aprovar e enviar:** **aprovação humana explícita** antes de qualquer envio. O boletim com IA
   nunca sai automaticamente.

**Divisão de responsabilidades:** o código executa cálculos e verificações; as regras selecionam os
destaques; a IA organiza a interpretação e redige; uma pessoa revisa e aprova.

---

## 6. Cuidados metodológicos para o recorte municipal

- O CAGED registra o vínculo no município do estabelecimento empregador, que não é necessariamente
  o de residência do trabalhador.
- Municípios pequenos podem apresentar taxas muito altas ou baixas por causa de poucas
  movimentações: mostrar também os valores absolutos.
- Um grande estabelecimento pode influenciar o resultado agregado: verificar a concentração
  setorial, sem inferir informações de empresas.
- Diferenciar os conceitos de vínculo, trabalhador e estabelecimento.
- Identificar a metodologia do estoque (reconstituição a partir de marco zero); não misturar
  metodologias sem explicitar.
- **Os últimos ~12 meses são provisórios:** declarações fora do prazo e exclusões ainda vão
  revisá-los. Registrar as revisões e manter uma série consistente.
- Considerar a mudança de metodologia na transição do CAGED antigo para o Novo CAGED (2020).
- Saldo de emprego formal não mede a ocupação total nem a taxa de desemprego do município.
- Não presumir que indicadores estaduais ou nacionais descrevem fielmente a atividade do município.

---

## 7. Checklist mensal de publicação

- [ ] Atualizar o CAGED do município e registrar a data da extração.
- [ ] Verificar revisões e consistência da série histórica.
- [ ] Calcular saldo, admissões, desligamentos e variação do estoque.
- [ ] Comparar com o mesmo mês de anos anteriores e calcular os acumulados.
- [ ] Identificar os grupamentos em destaque e, se relevante, a atividade dominante dentro deles.
- [ ] Verificar concentração, sazonalidade e efeitos de bases pequenas.
- [ ] Produzir a comparação sintética com a região e a UF.
- [ ] Atualizar o perfil das contratações e os salários de admissão (mediana e média).
- [ ] Consultar o perfil econômico municipal e definir os pontos de atenção (hipóteses só com evidência).
- [ ] Buscar evidências e acontecimentos com fonte e período identificados.
- [ ] Redigir a interpretação sem confundir associação com causalidade.
- [ ] Validar números, gráficos, fontes, datas e conclusões.
- [ ] Obter a aprovação humana antes de enviar.

---

## 8. Critério de qualidade do boletim

Cada edição deve responder, de maneira concisa:

1. **O que aconteceu** com o emprego formal no município?
2. **Onde aconteceu:** quais setores, e quando relevante quais atividades, foram responsáveis pelo
   resultado?
3. **É sazonal ou atípico** em relação ao histórico local? O número ainda é provisório?
4. **Como se compara** com a região e a UF?
5. **Quais evidências e acontecimentos** ajudam a contextualizar os movimentos selecionados?
6. **O que ainda é hipótese** e não pode ser afirmado como causa?

O boletim mantém um núcleo estatístico constante e varia apenas as investigações exigidas pelos
resultados do mês.

---

## Anexo: configuração da instância de Socorro

| item | valor |
|---|---|
| Município-alvo | Nossa Senhora do Socorro (280480) |
| Região | Região Metropolitana de Aracaju (RMA): Aracaju (280030), Barra dos Coqueiros (280060), Nossa Senhora do Socorro (280480) e São Cristóvão (280670), todos com marco zero |
| UF | Sergipe (28), com marco zero |
| Brasil | não disponível nesta instalação |

Este anexo é da instância e sai do roteiro na separação do produto ([F18](../fatias/F18-produto-neutro.md)).
