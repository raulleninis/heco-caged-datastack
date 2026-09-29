# F19 · Boletim analítico com IA

| | |
|---|---|
| **Status** | 🟡 em andamento: partes 1, 2 e 3 ✅; parte 4 começou pelo coletor de notícias (29/09/2026) |
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
| **Multiagente** | quatro agentes coordenados **por código**, em sequência fixa, com um contador de uso compartilhado (`usage=`) | previsível: nenhum agente decide chamar outro |
| **Modelos** | via **OpenRouter**; redator e revisor de **famílias diferentes**; escolha final por comparação prática (parte 6) | o custo por boletim é de centavos em qualquer modelo; o que diferencia é a qualidade do texto em português |
| **Banco** | **sem NL2SQL**: o analista usa ferramentas com consultas fixas, numa cópia do warehouse aberta só para leitura | o LLM não decide a conta; evita ler arquivos arbitrários e o conflito de trava com o pipeline |
| **Busca na web** | na v1, pelo plugin da OpenRouter, só na tarefa do pesquisador, com teto de resultados | acontecimentos locais e externos, conforme noticiados (roteiro, seção 1.5) |
| **Orçamento** | **US$ 2/mês**, no código e como limite da chave na OpenRouter | o limite da chave vale mesmo se o código falhar |
| **Envio** | **aprovação humana explícita**; o boletim com IA nunca sai automaticamente | interpretação com hipóteses não sai sem revisão |

Substitui o plano original com CrewAI (CLAUDE.MD, roadmap do README).

## Arquitetura

```
fatos (código, parte 1) ──► analista ──► pesquisador ──► redator ──► revisor ──► verificador ──► aguardando aprovação
   JSON com id por número    escolhe o     busca na web    texto do     parecer     números por
                             que           e APIs          boletim      (outra      código
                             desagregar    oficiais                     família)
                             (consultas
                             fixas)
```

- **Analista:** recebe os fatos e os gatilhos já calculados; pode pedir desagregações, mas só entre consultas pré-escritas e testadas.
- **Pesquisador:** busca indicadores por API oficial (IBGE, Banco Central) e acontecimentos na web, com fonte e data.
- **Redator:** escreve o boletim seguindo o roteiro. O verificador de números é o seu `output_validator`: número fora da tabela de fatos gera uma nova tentativa (`ModelRetry`), com teto.
- **Revisor:** de outra família de modelos. Confere linguagem causal, fontes, datas e se cada hipótese está rotulada.

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
| busca | teto de resultados por execução; o custo da busca entra no registro mensal |
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
- O pesquisador fica para a parte 4, junto com as evidências externas: sem elas, o redator
  é instruído a não citar fonte nem acontecimento.

### 4. Evidências externas

APIs oficiais (SIDRA/IBGE, SGS/Banco Central) buscadas por código, e a busca na web do pesquisador com teto de resultados. Cada evidência traz fonte, período e escala.

**Ordem revista (29/09/2026):** coletor diário de notícias → 3b-1 (editorial e fatos, a partir
da revisão do primeiro boletim) → parte 4 (triagem pelo Jev, pesquisador) → 3b-2 (advisor e
tickets).

**Coletor diário (feito, 29/09/2026):** `flows/noticias.py`, no início do flow diário.
- Fontes avaliadas: Sebrae SE, Faxaju, Infonet e InfoMoney têm RSS; Observatório FIES e
  Fecomércio SE não têm (ficam para a busca na web restrita, se o plugin permitir); a lista da
  Prefeitura de Socorro é montada por JavaScript. NewsAPI descartada: o plano gratuito é
  proibido em produção e o pago custa US$ 449/mês.
- Os feeds guardam pouco (Infonet: 10 notícias em 2 dias): por isso a coleta é diária e
  acumula em `/data/noticias/AAAA-MM.jsonl`, que **não se regenera** (ressalva na D03).
- O feed "SE" do Sebrae mistura conteúdo de outros estados (itens de `sc.agenciasebrae`): a
  triagem precisa filtrar por território, não só por tema.
- Primeira coleta: 49 notícias. 11 testes.
- Acrescentadas (29/09/2026): g1 Sergipe (100 notícias em ~11 dias) e g1 Economia (nacional).
  Recusadas: g1 geral (100 notícias em 3,5 horas, ruído) e a busca RSS do Google News, cujo
  robots.txt proíbe robôs em todo o site (com bloqueio explícito a robôs de IA); o coletor
  respeita o robots.txt. Deduplicação também pelo título normalizado, para a mesma notícia
  vinda por duas fontes. Total acumulado: 247 notícias.

### 5. Aprovação e envio

Estado `aguardando_aprovacao` no arquivo da F15, um comando de aprovação e o PDF do boletim com IA. O envio automático ignora esse estado.

### 6. Comparação de modelos

O boletim de 2 ou 3 competências passadas gerado com 3 candidatos, comparados pelo verificador e por leitura humana. Custo esperado: menos de US$ 1. Define os modelos do redator e do revisor.

## Fora de escopo

- Consultas SQL geradas pelo LLM.
- Identificação de empresas, em qualquer forma ([D10](../decisoes/D10-escopo-analitico.md)).
- Envio sem aprovação.
