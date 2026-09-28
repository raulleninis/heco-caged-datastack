# Auditoria do Novo Caged — Nossa Senhora do Socorro/SE

> **Nota de arquivamento:** relatório copiado como foi produzido. Os arquivos de evidência
> citados (CSVs, JSONs, respostas do painel e scripts `audit_*.py`) **não estão versionados**
> neste repositório; os nomes ficam aqui só como registro. Acrescentados depois, em 28/09/2026:
> a hipótese de imputação e a [decisão tomada](#decisão-tomada-28092026).

Consulta realizada em 28/09/2026. Município: 280480 (UF 28). Comparação: janeiro de 2020 a dezembro de 2025, por competência da movimentação e pelos cinco grandes grupamentos. A coluna `grupamento` do projeto corresponde a `Grande Grupamento` no painel.

## Resultado

**Somente janeiro e março de 2020 divergem. Os outros 70 meses coincidem em admissões, desligamentos e saldo, tanto por grupamento quanto no total municipal.**

Foram verificadas 360 combinações de mês e grupamento; 10 divergem. Combinações sem movimentações nas duas fontes foram representadas por zero. Os meses de 2026 não integram o diagnóstico de divergências. Os ajustes divulgados em 2026 foram considerados para as competências anteriores.

| Competência | Admissões local | Admissões painel | Desligamentos local | Desligamentos painel | Saldo local | Saldo painel |
|---|---:|---:|---:|---:|---:|---:|
| 202001 | 489 | 497 | 535 | 531 | -46 | -34 |
| 202003 | 378 | 377 | 404 | 405 | -26 | -28 |

Diferenças abaixo seguem **local menos painel**:

| Competência | Grupamento | Δ admissões | Δ desligamentos | Δ saldo |
|---|---|---:|---:|---:|
| 202001 | Agropecuária | 0 | -1 | +1 |
| 202001 | Comércio | -19 | -28 | +9 |
| 202001 | Construção | -10 | 0 | -10 |
| 202001 | Indústria | +2 | +1 | +1 |
| 202001 | Serviços | +19 | +32 | -13 |
| 202003 | Agropecuária | -1 | 0 | -1 |
| 202003 | Comércio | -16 | -28 | +12 |
| 202003 | Construção | +2 | 0 | +2 |
| 202003 | Indústria | -1 | 0 | -1 |
| 202003 | Serviços | +17 | +27 | -10 |

Os valores locais, oficiais e diferenças estão em `comparacao_grupamentos.csv` e `comparacao_totais.csv`.

## O que foi comprovado

1. **O mart já contém os ajustes.** A implementação utiliza `MOV + FOR − EXC`, agrupada pela competência da movimentação. A recomposição independente das três tabelas staging reproduziu o mart sem diferenças. Não foram reaplicados ajustes ao resultado do mart.
2. **O sinal das exclusões é consistente.** Nas 284 linhas EXC, o sinal armazenado corresponde ao evento original; o mart inverte seu efeito. Os indicadores de exclusão são 1. O problema encontrado não exige inverter novamente o EXC.
3. **A cobertura está completa até julho de 2026:** 79 competências MOV, 78 arquivos FOR (202002–202607) e 76 EXC (202004–202607). A listagem do FTP confirma os arquivos esperados. Arquivos sem eventos municipais também foram verificados.
4. **Todos os 154 FOR/EXC foram baixados novamente e conferidos.** Para Socorro, cada arquivo coincide com sua staging em contagens por competência da movimentação, subclasse CNAE, seção e sinal. Total: 2.746 linhas FOR e 284 EXC. Evidências em `ftp/adjustments/summary.json`, com hashes SHA-256 e resultados por arquivo.
5. **Os MOV atuais de janeiro e março também coincidem com a staging.** São 969 e 723 linhas municipais, respectivamente, com igualdade das contagens por subclasse, seção e sinal. Evidências em `ftp/comparison.json`. Os demais MOV não foram baixados novamente, pois seus resultados reconciliados coincidiram com o painel.
6. **A classificação local é coerente com os próprios microdados.** Não houve incompatibilidade de grande grupamento ao comparar a seção com a divisão obtida da subclasse CNAE nas três stagings. Isso não comprova que o cadastro publicado esteja atualizado; comprova que a regra local respeita os códigos publicados.
7. **O recorte geográfico está correto.** As stagings aplicam UF 28 e município 280480. O SQL apresentado pelo usuário pode dispensar filtro municipal nessa base específica, pois ela já é municipal.
8. **Os totais do painel foram conferidos por consulta independente**, sem dimensão econômica, e coincidem com a soma dos grupamentos extraídos. Não há diferença causada pelo `ROLLUP`.

Conclusão comprovada: **os microdados atualmente publicados no FTP, processados pela regra do projeto e incluindo todos os FOR/EXC disponíveis até 202607, não reproduzem o painel nesses dois meses.** Não foi encontrado erro de carga ou da fórmula de reconciliação que explique essas diferenças.

## Causa mais provável e seus limites

**A hipótese mais forte é uma diferença de versão/revisão dos MOV de janeiro e março de 2020 entre o FTP e a base que alimenta o painel.**

O FTP informa as seguintes datas de modificação (formato original MM-DD-YY):

| Arquivo | Data informada pelo FTP |
|---|---|
| CAGEDMOV202001.7z | 21/06/2022 |
| CAGEDMOV202002.7z | 08/06/2026 |
| CAGEDMOV202003.7z | 21/06/2022 |
| CAGEDMOV202004.7z | 08/06/2026 |
| CAGEDMOV202012.7z | 08/06/2026 |

As listagens originais estão em `ftp/adjustments/AAAAMM_listing.txt`. A data do arquivo é um indício, não uma identificação formal da versão metodológica. O modelo do painel registra última atualização em 28/08/2026 e apresenta julho de 2026 como última competência; o banco local também chega a julho de 2026.

O detalhamento por CNAE reforça a hipótese de revisão cadastral. Por exemplo:

| Competência | CNAE | Admissões local/painel | Desligamentos local/painel |
|---|---|---:|---:|
| 202001 | 6463800 | 19 / 0 | 26 / 0 |
| 202001 | 4691500 | 1 / 20 | 2 / 28 |
| 202003 | 6463800 | 18 / 0 | 27 / 0 |
| 202003 | 4691500 | 2 / 20 | 1 / 28 |

Essas diferenças se compensam entre Serviços e Comércio para essas duas subclasses. O padrão é **compatível com reclassificação de atividade econômica**, mas os microdados não identificados e as consultas agregadas não permitem afirmar que sejam os mesmos trabalhadores ou estabelecimentos. Existem outras diferenças e alterações no total municipal, portanto não basta transferir esses valores entre os dois grupamentos.

O MTE documenta substituições históricas de arquivos e correções de localização e outras variáveis no [Comunicado nº 1](https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/acoes-e-programas/programas-projetos-acoes-obras-e-atividades/estatisticas-trabalho/comunicados/1848-comunicado-atualizacoes-nos-microdados-do-novo-caged). Esse comunicado contextualiza a possibilidade de revisão; não comprova qual revisão explica especificamente Socorro em janeiro e março de 2020.

### Hipótese complementar: imputação na transição para o eSocial

Nos primeiros meses do Novo CAGED, o MTE (então SEPRT) complementou o eSocial com dados de
outras fontes por imputação. Se o painel incorpora registros imputados que não estão nos
`CAGEDMOV` publicados no FTP, isso explicaria parte da diferença.

**O que a fonte diz.** O [Guia metodológico para entender o Novo CAGED](https://www.ieri.ufu.br/system/files/conteudo/cepes_mt_guia_metodologico_do_novo_caged_2020_julho.pdf)
(CEPES/IERI/UFU, jul/2020, p. 2) cita a nota técnica da SEPRT de 27/05/2020:

> "a SEPRT observou a falta de prestação de informações relativas aos desligamentos no novo
> sistema e, tendo em vista isso, bem como com o intuito de mitigar possíveis inconsistências
> provenientes do processo de migração, a secretaria passou a empregar, então, um método de
> imputação de dados de diversas fontes, consolidando as estatísticas no que ficou conhecido
> como: Novo Caged. Este reúne, então, as informações do eSocial, do Caged (já que ainda há
> grupos de empresas que não estão obrigados ao eSocial) e do Empregador Web"

O mesmo guia associa o volume maior de declarações fora do prazo ao "período de adaptação
dos declarantes ao novo sistema".

**O que é compatível com os dados.**

- A imputação a partir de fontes fora do eSocial está documentada, e ocorreu justamente em 2020.
- Os dois arquivos divergentes (`CAGEDMOV202001` e `202003`) são os únicos, entre os listados,
  com data de 2022 no FTP; fev, abr e dez/2020 foram substituídos em 08/06/2026. Um
  reprocessamento que o painel incorporou e o FTP não republicou para esses dois meses é
  coerente tanto com esta hipótese quanto com a de versão.

**O que não se confirma, ou pesa contra.**

- **Fonte secundária.** O guia é da UFU, não do MTE. A nota técnica original da SEPRT não foi
  lida: o endereço no pdet.mte.gov.br não respondeu na consulta.
- **Não diz quais meses foram imputados**, nem se os registros imputados ficam fora dos
  microdados.
- **Fevereiro de 2020 também é de transição e coincide** com o painel. Ser mês de transição não
  basta para explicar a divergência.
- **O padrão principal é uma troca, não um acréscimo.** O painel tem mais movimentações em
  Comércio e menos em Serviços (CNAE 4691500 × 6463800), o que se parece mais com
  reclassificação. O efeito líquido no total é pequeno (jan: painel +8 admissões, −4
  desligamentos; mar: −1 e +1). A imputação explicaria, no máximo, esse resíduo líquido.
- 2026 ficou fora do diagnóstico. A comparação de 2020–2025 é a que mostra os outros 70 meses
  coincidindo.

**Leitura conjunta:** as duas hipóteses não se excluem. O mais provável é que o painel reflita
um reprocessamento de jan e mar/2020, com reclassificação de atividade e possivelmente
imputação, que não chegou aos arquivos do FTP. Só o MTE/PDET pode confirmar.

**Limite da conclusão:** está demonstrada a inconsistência entre as publicações. A razão administrativa/técnica pela qual esses dois MOV diferem da base do painel precisa ser confirmada pelo MTE/PDET; não há histórico de versões suficiente para identificá-la definitivamente.

## Encaminhamento recomendado

- Solicitar ao MTE/PDET os MOV revisados de 202001 e 202003 ou esclarecimento da diferença entre o FTP e o painel, anexando os CSVs e hashes desta auditoria.
- Enquanto isso, se o produto precisar reproduzir exatamente o painel, manter uma camada explícita de valores oficiais por competência e grupamento, com fonte e data de consulta. Preservar a reconciliação dos microdados para rastreabilidade; não inserir eventos fictícios nem ajustar arbitrariamente FOR/EXC.
- Acrescentar ao controle de ingestão nome do arquivo, tamanho, data de modificação FTP e SHA-256. Atualmente, `arquivos_ja_ingeridos()` pula arquivos já carregados e a rotina diária procura lacunas nos últimos seis meses: uma substituição histórica pode passar despercebida. É uma fragilidade preventiva identificada, **não a causa comprovada deste caso**, pois os arquivos atuais foram confrontados e coincidem com a carga.
- Manter uma comparação periódica com o painel. Os testes aritméticos existentes garantem coerência interna, mas não igualdade com uma publicação externa.

## Decisão tomada (28/09/2026)

> **O estoque de emprego parte do painel do MTE ao fim de mar/2020, e as movimentações dos
> microdados são aplicadas a partir de abr/2020.** Registrada em
> [D11](../decisoes/D11-estoque-de-emprego.md); implementação na
> [F16](../fatias/F16-estoque-a-partir-do-marco-zero.md).

- **Marco zero:** estoque do painel na competência 202003, por grande grupamento, para Socorro
  (280480), Aracaju (280030), Barra dos Coqueiros (280060), São Cristóvão (280670) e Sergipe
  (28). Valores, fonte e normalização em [marco-zero/FONTE.md](../../marco-zero/FONTE.md).
- **Por que resolve:** jan e mar/2020 ficam antes do ponto de partida. A série de estoque só
  usa meses em que o mart coincide com o painel, e a decisão vale para qualquer das duas
  hipóteses acima, porque o painel já inclui o que quer que explique a diferença.
- **Conferência:** para Socorro, estoque de jan (painel) + saldo de fev (mart) + saldo de mar
  (painel) = estoque de mar (painel), em todos os grupamentos (22.014 + 15 − 28 = 22.001). O
  "estoque" do painel é o do fim do mês, e o painel inclui as mesmas retificações que o mart.
- **Retificações:** o marco zero já contém os FOR/EXC de competências até 202003 publicados até
  202607 (em Socorro, 300 linhas, efeito −106). O ajuste do marco zero só usa os que chegarem em
  arquivos **posteriores a 202607**, para não contar duas vezes.
- **Fluxo de jan e mar/2020:** continua o dos microdados, sem ajuste nem eventos fictícios; a
  divergência fica documentada aqui.
- **Pendente:** pedido de esclarecimento ao MTE/PDET.

O banco original e os arquivos do pipeline não foram modificados.

## Evidências e reprodução (não versionadas)

- Comparação de 72 totais mensais: `comparacao_totais.csv`.
- Comparação de 360 combinações de mês e grupamento: `comparacao_grupamentos.csv`.
- Diferenças detalhadas por CNAE: `divergencias_cnae.csv`.
- Verificações locais: `local_checks.json`.
- Conferência dos dois MOV: `ftp/comparison.json`.
- Conferência dos 154 FOR/EXC: `ftp/adjustments/summary.json`.
- Requisição ao painel e resposta original: `panel/audit_request.json`, `panel/audit_response.json`.
- Requisição independente dos totais e resposta: `panel/audit_request_totals.json`, `panel/audit_response_totals.json`.
- Detalhamento por CNAE: `panel/audit_response_detail.json`.

Fonte de referência: [painel oficial indicado pelo usuário](https://app.powerbi.com/view?r=eyJrIjoiNWI5NWI0ODEtYmZiYy00Mjg3LTkzNWUtY2UyYjIwMDE1YWI2IiwidCI6IjNlYzkyOTY5LTVhNTEtNGYxOC04YWM5LWVmOThmYmFmYTk3OCJ9). Microdados: `ftp://ftp.mtps.gov.br/pdet/microdados/NOVO CAGED/`.

Os scripts `audit_*.py` registram a extração e as verificações. Usam conexão DuckDB somente leitura. `audit_compare.py` reconstrói os CSVs a partir da resposta oficial salva; `audit_detail.py` verifica a soma dos grupamentos contra os totais consultados separadamente. A resposta pública contém também 2026, mas esses meses são excluídos da comparação solicitada.
