# F19 · Boletim analítico com IA

| | |
|---|---|
| **Status** | 🟡 em andamento: partes 1 a 5 e 3b-2 ✅ (29/09/2026); falta a parte 6 |
| **Esforço** | XL, em partes independentes |
| **Fase** | produção / vitrine |
| **Depende de** | [F16](F16-estoque-a-partir-do-marco-zero.md) (estoque e territórios), [F15](F15-entrega-por-email-e-arquivo.md) (arquivo e envio) |
| **Roteiro** | [docs/boletim-ia/roteiro.md](../boletim-ia/roteiro.md): o que o boletim contém e as regras de redação |
| **Objetivo** | Um boletim mensal com interpretação redigida por IA sobre fatos calculados por código, com gasto limitado e aprovação humana antes do envio |

## Decisões (29/09/2026)

| tema | decisão | por quê |
|---|---|---|
| **Onde vive** | no **produto neutro** ([F18](F18-produto-neutro.md)); o boletim de Socorro fica na instância | o método é genérico e não expõe Socorro; o resultado é que expõe |
| **Framework** | **PydanticAI**, versão fixada com `==` | limites de uso nativos (`UsageLimits`, com `cost_limit`), saída tipada e validada, testes sem gastar tokens, 22 pacotes e 87 MB instalado (o CrewAI tem 148 e 959 MB), integração com Prefect |
| **Multiagente** | agentes coordenados **por código**, em sequência fixa, com um contador de uso compartilhado (`usage=`) | previsível: nenhum agente decide chamar outro |
| **Modelos** | via **OpenRouter**; redator e revisor de **famílias diferentes**; escolha final por comparação prática (parte 6) | o custo por boletim é de centavos em qualquer modelo; o que diferencia é a qualidade do texto em português |
| **Banco** | **sem NL2SQL**: o analista usa ferramentas com consultas fixas, numa cópia do warehouse aberta só para leitura | o LLM não decide a conta; evita ler arquivos arbitrários e o conflito de trava com o pipeline |
| **Notícias** | **nenhuma** (decisão de 30/09/2026): sem busca na web, sem coletor, sem pesquisador | o boletim descreve os dados, sem explicar causas |
| **Orçamento** | **US$ 2/mês**, no código e como limite da chave na OpenRouter | o limite da chave vale mesmo se o código falhar |
| **Envio** | **aprovação humana explícita**; o boletim com IA nunca sai automaticamente | interpretação redigida por IA não sai sem revisão |

Substitui o plano original com CrewAI (CLAUDE.MD, roadmap do README).

## Arquitetura

```
fatos (código, parte 1) ──► analista ──► redator ──► revisor ──► verificador ──► aguardando aprovação
   JSON com id por número    escolhe o     texto do     parecer     números por
   + Pix e Selic (código)    que           boletim      (outra      código
                             desagregar                 família)
                             (consultas
                             fixas)
```

- **Analista:** recebe os fatos e os gatilhos já calculados; pode pedir desagregações, mas só entre consultas pré-escritas e testadas.
- **Redator:** escreve o boletim seguindo o roteiro. O verificador de números é o seu `output_validator`: número fora da tabela de fatos gera uma nova tentativa (`ModelRetry`), com teto.
- **Revisor:** de outra família de modelos. Confere números, linguagem causal, identificação, estrutura e estilo.
- **Em volta:** o Jev (juiz) tria as dúvidas do analista e julga as afirmações do redator; o advisor responde dúvidas de método; dúvidas de fato local viram tickets (3b-2).

## Proteções contra gasto

| camada | proteção |
|---|---|
| provedor | chave dedicada na OpenRouter com **limite de crédito mensal** (US$ 2) |
| chamada | `max_tokens` fixo por agente; esforço de raciocínio limitado; tempo limite; `per_request_input_tokens_limit` |
| execução | `UsageLimits` compartilhado entre os agentes: `request_limit` (o padrão 50 cai para ~8), `tool_calls_limit`, `total_tokens_limit` e `cost_limit` |
| mês | registro local do custo real informado em cada resposta; recusa ao passar do orçamento |
| repetição | mesmo mês com os mesmos fatos reaproveita o resultado; só gera de novo com `--refazer` |
| modelo | lista de modelos permitidos no `.env` |
| saída | tipo Pydantic + verificador de números; uma nova tentativa e, depois, revisão humana com o relatório de erros |
| envio | aprovação humana |

## Partes

### 1. Fatos, sem LLM

Tudo por código, testado, e útil mesmo sem IA:

- **`mart_fluxo`:** admissões, desligamentos e saldo **reconciliados** (MOV + FOR − EXC) por território × competência × grupamento × subgrupamento × divisão CNAE. A soma por grupamento confere com o `mart_estoque`.
- **`mart_perfil_admissoes`:** admissões reconciliadas por território × competência × sexo e × faixa etária.
- **Regiões:** seed `regioes.csv` (na instância de Socorro, a RMA) e o estoque da região como soma dos municípios, cada um com seu marco zero.
- **Fatos do mês (JSON):** panorama, acumulados no ano e em 12 meses, decomposição, setorial, candidatos a desagregação, comparação município × região × UF, perfil, salário e **gatilhos** (sazonalidade pela faixa mínimo–máximo do mesmo mês desde 2020, base pequena, concentração), com a marca de provisório. Cada número tem um id, para o verificador.
- **Limiares** num arquivo do perfil municipal, da instância.

**Aceite:** os fatos de uma competência passada batem com o boletim atual onde se sobrepõem, e os testes cobrem os gatilhos.

**Feito (29/09/2026):**
- Marts `mart_fluxo`, `mart_perfil_movimentacoes`, `mart_estoque_regiao` e
  `mart_salario_admissao`, com a regra do estoque (`efeito_no_saldo(colunas)`). Testes
  singulares conferem o fluxo com o `mart_estoque` e com o `mart_caged_reconciliado`, o
  perfil com o fluxo, a região com a soma dos membros e o salário com a base por
  grupamento. Mutação de controle: com o peso do EXC quebrado,
  `test_fluxo_confere_reconciliado` acusa 55 linhas.
- `pipeline/flows/fatos.py`: o JSON de fatos, com 127 números registrados para Socorro em
  202607. Panorama idêntico ao painel do MTE (882 admissões, 965 desligamentos, saldo −83,
  estoque 25.439). 15 testes.
- Perfil de Socorro em `pipeline/perfis/280480.toml` só com limiares; a parte textual
  (cadeias produtivas, sazonalidades conhecidas) fica para a implantação, com fontes.

### 2. Cliente e proteções

Configuração da OpenRouter no PydanticAI, `UsageLimits`, registro mensal de custo, lista de modelos permitidos e reaproveitamento por hash dos fatos. **Aceite:** testes com `TestModel`/`FunctionModel`, sem chamar a API, provam que cada limite corta a execução.

**Feito (29/09/2026)** em `pipeline/flows/ia.py`, com 17 testes (`FunctionModel`, sem rede):

- **Achado:** o `cost_limit` do PydanticAI 2.51 calcula o custo pela tabela `genai-prices` e,
  para um modelo que ela não conhece, **não aplica o limite** (só avisa). O custo real da
  OpenRouter chega em `provider_details['cost']`, fora do contador. Por isso o teto em dólar
  é nosso:
  - **reserva do pior caso:** antes de rodar, a execução reserva `limites de tokens × preço`
    do modelo mais caro dela (preços da API pública da OpenRouter, cópia local de até 7 dias;
    sem preço, não roda). Com o Sonnet 5.5: US$ 0,44;
  - **registro:** `/data/ia/custos.jsonl` grava reserva, custo real de cada resposta e
    encerramento; uma reserva sem encerramento conta pelo máximo.
- Limites nativos que funcionam: requisições (8), tokens de entrada (120 mil) e de saída
  (20 mil) por execução, compartilhados entre os agentes; `max_tokens` e tempo limite por papel.
- Lista de modelos permitidos vazia por padrão, e teto de preço de saída por modelo (US$ 15/M).
- O reaproveitamento por hash dos fatos fica para a parte 3, onde está o orquestrador.

### 3. Agentes e verificador

Os quatro agentes, o verificador de números como `output_validator` e as instruções derivadas do roteiro. **Aceite:** com um modelo falso que inventa um número, o verificador o rejeita e a execução termina em revisão humana, sem passar do teto.

**Feito (29/09/2026)**, com 11 testes (`FunctionModel` roteirizado, sem rede):

- `flows/verificador.py`: todo número do texto está em `numeros` (formato BR, sinal por
  extenso, arredondamento de % e R$, "mil"); anos e inteiros de 1 a 12 livres; sinaliza
  forma jurídica e CNPJ.
- `flows/boletim_ia.py`: analista, redator e revisor com saídas Pydantic, `retries=1`. O
  verificador é o validador do redator; na última tentativa o texto é aceito como
  `reprovado_no_verificador`, com o relatório, em vez de abortar. Problema grave do revisor
  gera uma segunda versão, verificada de novo. Pior caso: 7 requisições (limite 8).
- Reaproveitamento pelo hash dos fatos; `--refazer` força.
- Sem pesquisador: o redator é instruído a não citar notícias nem acontecimentos.

### 4. Indicadores oficiais

> **Notícias: tentadas e removidas (29 e 30/09/2026).** A parte 4 chegou a ter coletor diário de
> feeds, triagem pelo Jev, pesquisador e "Leituras relacionadas". Saiu tudo em 30/09/2026: o
> boletim descreve os dados, sem hipóteses, e as notícias traziam ruído (na única execução
> completa, a única notícia relevante era publicidade) e manutenção de fontes. Ficou do trabalho
> o Jev como juiz (papel `juiz` da Execucao: preço pela consulta direta ao modelo, teto de 60
> decisões e de 30 mil tokens por decisão, preço variável −1 recusado) e a lição de que ele é
> sensível à redação da pergunta: limiares só com calibração em casos rotulados (parte 6). O
> detalhe está no histórico do git.

**3b-1, editorial e fatos (feita, 29/09/2026)**, a partir da revisão editorial do primeiro boletim:
- Fatos: rótulos de mês ("julho de 2025"), faixa histórica citável com o período, saldo dos dois
  meses anteriores, saldo dos grupamentos fora dos destaques e do restante de um grupamento,
  variação nominal da mediana, variação de participação em pontos percentuais, categorias
  relevantes do perfil e nomes curtos dos subgrupamentos, todos por código. A contribuição
  percentual e a participação nas movimentações em 12 meses passaram para `apoio` (uso interno,
  não publicáveis).
- Verificador: números de rótulos ("18 a 24 anos") só valem nessa posição; avisos de estilo
  (travessão, expressões de IA, percentual sem 2 casas, "mesmo mês do ano anterior",
  provisório repetido), que nunca geram nova tentativa.
- Redator: estrutura fixa (síntese, panorama, setores, contexto regional, perfil e remuneração,
  pontos de atenção, nota metodológica), sem hipóteses, regras editoriais com a versão compacta
  da humanizer. Tabelas geradas por código. Revisor com os fatos completos e os avisos de estilo.
  Modelos de decisão recusados nos papéis de texto. Rejeições do verificador registradas.
- Segunda execução real (202607, mesmos modelos): US$ 0,028 (a primeira custou US$ 0,094), 1 min
  55 s, nenhuma rejeição do verificador, uma versão só (nenhum problema grave), 7 apontamentos
  menores do revisor, 2 avisos de estilo.

**3b-2, decisão e tickets (feita, 29/09/2026)**, a partir das sugestões do usuário (advisor,
agir pelo grau de certeza, tickets com estado salvo, registro de decisões):
- A certeza que o LLM declara é mal calibrada; quem decide é o código, com o Jev: ele classifica
  as dúvidas do analista (fato local, método, nenhuma) e julga se os fatos citados sustentam cada
  afirmação interpretativa do texto. As não sustentadas vão destacadas para a revisão humana.
- Dúvida de método vai ao advisor (Sonnet 5.5; no máximo 2). Dúvida de fato local vira ticket:
  a execução para com a análise salva; respondida, retoma sem pagar o analista de novo, e a
  resposta entra na base de conhecimento local dos boletins seguintes.
- Registro de decisões no resultado (triagens, retomadas, julgamentos, com probabilidades).
- Primeira execução real: o advisor deu orientações de método precisas (não falar em tendência
  com competência provisória; Pix e saldo medem coisas e períodos diferentes); o Jev concordou
  com o analista nas três dúvidas; uma virou ticket. A pergunta do ticket puxava para
  "um ou poucos estabelecimentos": as instruções do analista passaram a proibir dúvidas sobre
  empresas ou estabelecimentos.

**Indicadores oficiais (feitos, 29/09/2026):** `flows/indicadores.py`, a pedido do usuário.
- Pix por município (Banco Central): o único dado de atividade econômica do próprio município,
  mensal e publicado antes do CAGED (em 29/09 já ia até setembro). Empresas que receberam Pix e
  valor recebido por empresas, em município, região e UF, com a variação em 12 meses e a
  diferença do município para a UF em pontos percentuais, tudo por código. Em Socorro, julho de
  2026: 5.184 empresas, +21,75% em 12 meses, 3,66 pontos acima de Sergipe (a adoção do Pix
  explica boa parte da alta: por isso a leitura é relativa).
- Selic só com Construção ou Comércio em destaque; dólar fora (Socorro não tem cadeia
  exportadora relevante). IBGE fora: os dados não descem a município ou saem com pouca
  frequência.
- Execução real em produção (202607): o Pix entrou nos pontos de atenção com leitura relativa e
  os cuidados na nota metodológica; nenhum número reprovado no final.

### 5. Aprovação e envio

Estado `aguardando_aprovacao` no arquivo da F15, um comando de aprovação e o PDF do boletim com IA. O envio automático ignora esse estado.

**Feita (29/09/2026)**, com 7 testes, em `flows/entrega_ia.py`, com uma lista de
administradores pedida pelo usuário:
- `revisar`: gera o PDF uma única vez e envia só aos administradores
  (`secrets/destinatarios_admin.txt`), com o relatório de revisão (parecer, verificador,
  avisos de estilo, afirmações não sustentadas). O PDF não leva marca de rascunho: ela vai no e-mail, porque
  regenerar o PDF mudaria os bytes.
- `aprovar --por "Nome"`: só o que está em revisão, com o sha256 do PDF revisado.
- `enviar`: arquiva e envia à lista principal o mesmo PDF (confere o sha256), com as
  garantias da F15 e a chave `ia-AAAAMM`; o índice do arquivo ganha o link.
- Resultado reprovado no verificador não vai à revisão. Nada é automático.
- PDF do resultado real de 202607: duas páginas, texto e tabelas por código, aviso de uso de IA.

### 6. Comparação de modelos

O boletim de 2 ou 3 competências passadas gerado com 3 candidatos, comparados pelo verificador e por leitura humana. Custo esperado: menos de US$ 1. Define os modelos do redator e do revisor.

**Calibração do Jev (feita, 29/09/2026):** `flows/calibracao.py`. 130 afirmações de resposta
conhecida (7 competências). Acima de 0,6, todas as afirmações eram verdadeiras; o Jev
recusou as 14 com causa; excelente em sinal, faixa e perfil, razoável em comparação, falha em
direção temporal (mesmo citando os níveis). Limiar das afirmações 0,6; "subiu/caiu" fora da
lista do redator.

**Comparação de redatores (rodada em 29/09/2026):** `flows/comparacao_modelos.py`, Gemini 3.7
Flash, Sonnet 5.5 e GLM 5.3 Flash, junho e julho de 2026, às cegas (leitura.md, métricas e
gabarito em arquivos separados). US$ 0,36. Uma geração falhou no ANALISTA (fixo em todas), não no
redator: o GLM 5.3 Flash devolveu saída fora do esquema 3 vezes no dia (2 como revisor, 1 como
analista). Revisor e advisor passaram a não ser fatais (boletim segue com o aviso). Escolha do
redator pendente da leitura humana.

**Revisão editorial de 30/09/2026 (feita):** o problema era redundância, não prolixidade: o
texto lia as tabelas em voz alta.
- Estrutura: resumo em uma frase (sem estoque) → evolução do emprego → setores → comparação
  regional e perfil → o que acompanhar → tabelas → indicadores complementares → nota.
- `numeros_do_texto` (por código) diz ao redator o que o texto pode citar; o resto fica nas
  tabelas, e `verificador.numeros_de_tabela` gera aviso de estilo quando o texto repete (3 avisos
  já pedem segunda versão). No boletim anterior de julho seriam 27 avisos.
- Faixa histórica só pela posição, sem os limites; demais grupamentos só pelo saldo conjunto;
  comparação regional numa frase sem números; perfil pelas maiores perdas e pelas participações.
- Pix fora do texto e do prompt: quadro "Indicadores complementares" com o cuidado de leitura.
- Nota metodológica por código (4 frases); aviso de IA encurtado.
- Teto do analista: 3 mil tokens (2 mil estourava em 3 de 15 chamadas do GLM 5.3 Flash).
- Prévia real (202607, `--sem-tickets`): US$ 0,024, 1 aviso de estilo, uma versão só. O revisor
  ainda aponta verbos de causa ("decorreu de", "determinado por") como menores.

## Fora de escopo

- Consultas SQL geradas pelo LLM.
- Identificação de empresas, em qualquer forma ([D10](../decisoes/D10-escopo-analitico.md)).
- Envio sem aprovação.
