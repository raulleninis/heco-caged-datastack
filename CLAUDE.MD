# CAGED Analytics — contexto para agentes de IA

## Objetivo
Pipeline de dados educacional/portfólio: ingestão, transformação e (em breve)
geração de relatório mensal automatizado sobre o mercado de trabalho formal
de Nossa Senhora do Socorro/SE, a partir dos microdados do Novo CAGED (PDET).

## Stack
- Ubuntu Server 24.04 LTS headless, acesso só via SSH (chave) + Tailscale
- Docker Compose (plugin v2, comando `docker compose`, sem hífen)
- DuckDB — único armazenamento de dado (staging + mart no mesmo arquivo .duckdb)
- dbt-core + dbt-duckdb — transformação e testes de qualidade
- Prefect 3.x — orquestração, backend SQLite com volume nomeado para persistência
- Pipeline executa em container não-root (UID 1000)
- Versões pinadas (`==`), sem pandas: prefect==3.8.0, dbt-core==1.12.0,
  dbt-duckdb==1.10.1, duckdb==1.5.5, py7zr==0.22.0 (ver F08). Imagem base
  `python:3.11.10-slim-bookworm` e `prefecthq/prefect:3.8.0-python3.11`
  também pinadas — nenhuma tag flutuante (`:latest`, `:slim`) no projeto.

## Decisão de arquitetura importante
Postgres e Metabase foram removidos deliberadamente. Não recomendar
reintroduzi-los sem necessidade explícita — DuckDB sozinho é suficiente
porque não há consumidor com conexão persistente (ver restrição abaixo).

## Restrição técnica não óbvia
DuckDB só permite OU múltiplos leitores (read-only) OU um único processo
em leitura-e-escrita — nunca os dois ao mesmo tempo. Qualquer processo que
abrir o .duckdb pra leitura de forma persistente (ex.: um dashboard) impede
escrita em qualquer outro lugar até fechar a conexão.

## Estrutura
- `docker-compose.yml` — 2 serviços: prefect-server, pipeline
- `pipeline/prefect.yaml` — deployment declarativo (cron schedule, work pool `default`)
- `pipeline/start.sh` — CMD do container: aguarda Prefect Server, aplica
  `prefect deploy --all`, inicia `prefect worker start --pool default`
- `pipeline/flows/alertas.py` — alerta ativo (`NTFY_URL`) e heartbeat externo
  (`HEARTBEAT_URL`), ambos opcionais; hook `alerta_falha` ligado aos dois flows
- `pipeline/docker-entrypoint.sh` — ENTRYPOINT: alinha UID/GID do usuário
  `caged` com o dono real de `/data` e `/dbt` (bind mounts) antes de rodar
  qualquer comando, depois dropa privilégio via `gosu`
- `pipeline/flows/ingest_caged.py` — flows com varredura de lacunas:
  - `ingest_caged()` — consumido pelo worker via deployment agendado, varre
    últimos 6 meses procurando faltantes
  - `backfill_caged(ano, tipos, refazer)` — execução manual via CLI
    (`python flows/ingest_caged.py backfill <ano | ano..ano> [--tipos MOV,FOR,EXC]
    [--refazer]`), varre o ano; pula o que já está carregado (`--refazer` reprocessa)
  - Ambos tratam **arquivos (tipo, competência)**, não só competências (F12): o PDET publica
    `CAGEDMOV` (dentro do prazo), `CAGEDFOR` (fora do prazo, soma) e `CAGEDEXC` (exclusões,
    subtrai) por competência de DECLARAÇÃO. Baixam → extraem → deletam .7z → `_transformar()`,
    que roda a staging UMA VEZ POR ARQUIVO (`dbt run --select stg_caged_<tipo> --vars
    '{"competencia_arquivo": "AAAAMM"}'`), registra o arquivo em `ingestao_arquivos`, depois
    materializa o estoque de referência e os marts (`stg_estoque_referencia path:models/marts`) uma vez e roda os testes (ver limitação de
    memória abaixo). FOR e EXC são pequenos (~1 MB / 0,1 MB o .7z); só o MOV pesa (~45 MB)
- `pipeline/flows/boletim.py`, `arquivo.py`, `entrega.py` — entrega por e-mail (F15):
  gera boletim (PDF) e planilha (XLSX) **do mart**, arquiva no repositório privado do
  arquivo (`arquivo/` aqui é o esqueleto dele, com o bloqueio do Netlify) e envia por SMTP,
  um e-mail por destinatário. Ver "Entrega por e-mail" abaixo
- Apresentação dos PDFs (design v3): `pdf_design.py` (componentes, fontes Archivo/IBM Plex Sans
  em `flows/assets/`, OFL), `pdf_automatico.py` (boletim da F15) e `pdf_analitico.py` (com IA).
  Marca da instância (território, instituição, órgão, logo) na seção `[identidade]` de
  `perfis/<territorio>.toml`; sem ela, sai neutro (F18). Fontes TTF: Unicode, sem `_latin1`.
  O selo "Protótipo" sai na 1ª página dos dois (`BoletimPDF(prototype=True)`). Mudar o design não
  regenera o que já está arquivado/aprovado: só `arquivar --refazer` ou nova revisão
- `dbt/models/staging/_sources.yml` — declara `caged_raw.caged_movimentacoes`
  como source; `external_location` usa `read_csv_auto(...,
  all_varchar=true)` parametrizado com `{{ var('competencia_arquivo', '*') }}`
  (todo YAML de projeto dbt passa pelo Jinja renderer, não só `.sql`) —
  sem var, lê tudo via glob; com var, restringe a um arquivo. SEM `freshness`
  de propósito: `dbt source freshness` lê o `.txt`, que é apagado após a
  transformação — a checagem de defasagem é `verificar_defasagem()` (F11)
- `dbt/models/staging/stg_caged_movimentacoes.sql` — materializada como
  `incremental` (`delete+insert`, `unique_key='competencia_mov'`), lê do
  source acima (tudo VARCHAR), faz CAST explícito por coluna, filtra uf=28
  (Sergipe inteiro, F16 parte 2; o município é filtrado nos marts), deriva `grupamento` e
  `subgrupamento`
- `dbt/tests/` — testes singulares: unicidade do grão do mart, coerência
  aritmética (`saldo_liquido = admissoes - desligamentos`), faixa plausível
  de salário (o teste que teria pego o bug de F05), salário individual
  (teto R$ 50.000 por admissão, pega outlier isolado na origem) e razão
  média/mediana (pega distorção moderada que a faixa absoluta deixa passar); estoque (F16):
  estoque não negativo, coerência, conferência com o estoque de referência (F20).
  Testes unitários do estoque em `models/marts/_marts.yml` (`unit_tests:`)
- `dbt/models/marts/mart_caged_mensal_grupamento.sql` — métricas por competência + grupamento:
  - `admissoes`, `desligamentos`, `saldo_liquido` (contagens)
  - `admissoes_com_salario_valido` (base do cálculo de salários)
  - `salario_mediano_admissao` (métrica robusta — referência)
  - `salario_medio_admissao` (para comparação com mediana)
  - `palma_index_admissao` (desigualdade: top 10% / bottom 40%)

## Comandos comuns
# Iniciar stack (Prefect Server + pipeline com deployment + worker)
docker compose up -d

# Backfill de um ano inteiro (manual, fora do schedule)
docker compose run --rm pipeline python flows/ingest_caged.py backfill 2026

# Disparar o ingest_caged do deployment agendado manualmente (sem esperar o cron)
docker compose exec pipeline prefect deployment run 'ingest-caged/caged-ingest-daily'

# Rodar dbt isoladamente — staging é incremental, uma competência por vez
docker compose run --rm pipeline dbt run --select stg_caged_movimentacoes \
  --vars '{"competencia_arquivo": "202608"}' --project-dir /dbt --profiles-dir /dbt
docker compose run --rm pipeline dbt run --select mart_caged_mensal_grupamento \
  --project-dir /dbt --profiles-dir /dbt
docker compose run --rm pipeline dbt test --project-dir /dbt --profiles-dir /dbt

# dbt run sem --select nem --vars roda a staging inteira via glob (*) — só
# use em dev/debug com poucas competências; nunca em produção (ver limitação
# de memória abaixo)

# Ver histórico de deployments no Prefect
curl -s http://localhost:4200/api/deployments/filter -X POST -H 'Content-Type: application/json' \
  -d '{"limit":10}' | python3 -m json.tool

## Gotchas da fonte de dados (PDET/Novo CAGED)
- Distribuído via FTP (ftp.mtps.gov.br), arquivo `.7z` (não `.zip`)
- Divulgação com ~1 mês de defasagem, sem dia fixo
  - Flow não assume data fixa: varre últimos 6 meses, procura lacunas
  - Se agosto atrasar (publicado em setembro), será ingerido no próximo run
- Colunas originais vêm acentuadas (ex. `salário`) — renomeadas para
  snake_case sem acento na staging
- `salario`, `valor_salario_fixo`, `horas_contratuais` usam vírgula decimal
  no arquivo bruto — precisam de `REPLACE(',', '.')` + `CAST` explícito
- Unidade de salário é heterogênea (hora, dia, semana, mês, etc)
  - Métricas de salário filtram só mensal (`unidade_salario_codigo = 5`)
  - Usam `valor_salario_fixo`, não `salario` genérico
  - Excluem valores ≤ 0 (significam "não informado" no CAGED declaratório)
  - Códigos observados em dados reais (202601-202607): 1,2,4,5,7,99 — 7 e 99
    não estão documentados no layout conhecido (1-6), mas aparecem nos dados
    (7 sempre valor=0; 99 majoritariamente 0, raramente não-zero). Não afetam
    o mart (filtra só código 5). Ver `_staging.yml` para accepted_values atual.

## Segredos
Tudo em `.env` (nunca commitado). `PREFECT_HOST` (IP Tailscale) e, opcionais,
`NTFY_URL` e `HEARTBEAT_URL` (F11). O nome do tópico ntfy funciona como senha.
Entrega (F15): `SMTP_*`, `EMAIL_*`, `ARQUIVO_*` (ver `.env.example`); deploy key e
lista de destinatários em `./secrets/` (montado em `/secrets`, somente leitura).

## Observabilidade e alertas (F11)
Três estados que antes davam o mesmo sinal (run verde) agora se distinguem:
- **Competência ainda não publicada** — verde, mas registrada (artifact
  `metricas-ingestao` no Prefect diz "nenhuma nova; última no warehouse: X")
- **Publicada e ingerida** — verde; artifact com MB baixados, linhas do
  município, tempos
- **Silêncio**: `verificar_defasagem()` roda em TODO run (inclusive sem nada
  novo) e levanta `DefasagemExcedida` se a competência mais recente no
  warehouse fechou há mais de 60 dias → run vermelho + alerta
Alertas ativos (ntfy): falha/crash de qualquer flow, defasagem, testes dbt em
WARN, volume de linhas < 50% da mediana das demais competências.
Heartbeat (dead-man's-switch, ex. healthchecks.io): ping ao fim de todo run
verde, `/fail` em falha. É o único alerta externo — o que avisa se o Prefect
ou a máquina inteira pararem. Sem as variáveis, o pipeline roda igual e loga
aviso. Testes dbt de plausibilidade (faixa, salário individual, média vs
mediana) são `severity: warn` (D04): não derrubam o flow nem bloqueiam a
deleção do `.txt`, mas geram alerta.

## Entrega por e-mail e arquivo (F15)
Desligada por padrão (`ENTREGA_HABILITADA=false`); o flow diário só a chama se ligada.
Ordem: `gera → arquiva → grava enviando → envia → grava enviado`, cada gravação é
commit + push no repositório privado do arquivo. Regras que não são óbvias:
- O estado (`envios.json`) vive no repositório do arquivo, **não no warehouse** (D03):
  apagar o `.duckdb` não reenvia nada. Sem conseguir ler esse estado, não envia.
- `enviando` que não virou `enviado` é **órfão**: nunca reenviar sozinho; alerta a cada
  run e a resolução é manual (ver `arquivo/README.md`). Duplicar e-mail é pior que atrasar.
- O que se anexa são os bytes **arquivados**, não uma regeneração (o CAGED revisa meses
  passados, ver F12). Só a competência mais recente do mart dispara envio automático.
- A lista de destinatários é dado pessoal (LGPD): `secrets/destinatarios.txt`, fora do
  git, assim como a deploy key (`secrets/arquivo_deploy_key`). Nunca logar endereços.
- O arquivo é servido em `https://caged.obsnss.space` (Netlify, DNS na Cloudflare; o remetente
  é `boletim@boletim.obsnss.space` via Resend e `contato@obsnss.space` é só encaminhamento para o Gmail).
  Os registros do Resend no DNS têm de ficar em "somente DNS" (sem proxy da Cloudflare).
- Manual (rode SEMPRE com `docker exec -u caged` ou `docker compose exec -u caged`: como root o clone
  do arquivo fica com dono root e o flow diário passa a falhar no git):
  - `python flows/entrega.py teste [AAAAMM]` — só para `EMAIL_TESTE`, não registra nada
  - `python flows/entrega.py enviar AAAAMM` — e-mail real, idempotente; reaproveita o que já está arquivado
  - `python flows/entrega.py arquivar 202001..202606 [--refazer] [--incluir-enviados]` — só gera e
    arquiva, **sem e-mail**, com `status: "arquivado"` no `envios.json`. O envio AUTOMÁTICO pula esse
    status (arquivar nunca vira e-mail); o `enviar` manual envia mesmo assim. Um commit para o lote;
    sem `--refazer` não sobrescreve nada. `--refazer` substitui o que está só arquivado (é o que se usa
    em desenvolvimento, para regenerar antes de abrir ao público). O que consta como ENVIADO é protegido:
    só é substituído com `--incluir-enviados`, e o registro do envio anterior fica em `substitui_envio`.
    Um envio `enviando` (órfão) nunca é tocado
  - `python flows/entrega.py remover AAAAMM [...] [--incluir-enviados]` — apaga do arquivo e do
    `envios.json` (continua no histórico do git)
- O DuckDB continua com um único escritor: o `teste`/`enviar` manual abre o warehouse
  só para leitura, mas não rode enquanto o flow diário estiver processando.

## Reconciliação FOR/EXC (F12)
- `dbt/macros/caged.sql` — colunas, CAST e grupamento compartilhados pelas três staging
  (`stg_caged_movimentacoes`, `stg_caged_fora_do_prazo`, `stg_caged_exclusoes`). FOR/EXC são
  incrementais por ARQUIVO (`unique_key='competencia_arquivo'`, vinda do nome via
  `filename=true`), porque um arquivo traz movimentações de VÁRIAS competências anteriores.
  Cada fonte tem padrão com prefixo (`CAGEDFOR*.txt`), então os tipos não se misturam na mesma pasta
- `mart_caged_reconciliado` (competência de movimentação × grupamento): `saldo_mov`,
  `saldo_fora_prazo`, `saldo_exclusoes` (JÁ com o efeito: o EXC preserva o sinal do evento
  excluído, então o efeito é o inverso) e `saldo_consolidado`, mais `situacao`
  (provisório se defasagem < `meses_para_consolidar`, padrão 12 = o máximo de atraso do FOR
  medido). "Consolidado" NÃO é imutável: o EXC retroage até 68 meses. Salários ficam só no mart do MOV
- Testes que travam as premissas: `test_exc_preserva_sinal_do_evento`, `test_coerencia_reconciliado`,
  `test_continuidade_mov` (erro) e `test_continuidade_for_exc` (warn: o PDET pode publicar FOR/EXC
  depois do MOV). O boletim (F15) usa o mart reconciliado e cai no só-MOV se ele não existir.
  Estoque e taxa (F16 parte 3, F20) vêm do mart_estoque, `TERRITORIO = "280480"` em boletim.py (tem de
  bater com a var municipio_boletim do dbt); só aparecem quando existem
- Filtro territorial (F16 parte 2): a staging guarda Sergipe inteiro (`uf = 28`, ~26 mil
  linhas/mês no MOV). `mart_caged_mensal_grupamento`, `mart_caged_reconciliado` e o teste de
  salário individual filtram `municipio = {{ var('municipio_boletim') }}` (280480, em
  dbt_project.yml). ARMADILHA: todo mart ou teste novo que leia a staging precisa filtrar o
  território, senão soma o estado inteiro em silêncio

## Estoque ancorado no estoque de referência do MTE (F20; marco zero F16 desativado)
- Âncora = **estoque de referência do MTE** (gov.br, NÃO está no FTP; um zip por ano, município ×
  subclasse CNAE; o de 2026 é o estoque ao fim de 202512). O painel do Novo CAGED faz igual:
  troca de referência desloca a série inteira até 2020. `mart_estoque`: referência +
  acumulado(t) − acumulado(ref), para trás e para frente, desde `var('estoque_inicio')` (202001).
  Conferido com o painel: de mar/2020 em diante bate; jan e fev/2020 de Socorro ficam 2 ABAIXO do painel
  (recuar passa pelo 202003 divergente do FTP, docs/auditorias/), diferença ACEITA pelo usuário.
  NULL sem referência ou com a referência à frente dos dados. Todo território com referência tem os seis grupamentos
- `flows/estoque_referencia.py` (`ANO_REFERENCIA = 2026`): todo run do flow confere o zip
  (SHA-256 do `.txt`; o gov.br não manda Last-Modified e dá 403 a HEAD: GET com User-Agent de
  navegador). Mudou → substitui `estoque_referencia` (só UF 28, numa transação), registra em
  `estoque_referencia_arquivos` e o flow roda `_materializar_marts()` mesmo sem competência
  nova. Ano novo publicado → aviso UMA vez (`estoque_referencia_avisos`); trocar o ano é manual
  (reancora tudo; conferir com o painel antes). Falha de rede nunca derruba o flow
- `stg_estoque_referencia`: subclasse vem sem zero à esquerda (lpad 7) → divisão → seção (seed
  cnae_divisoes) → `caged_grupamento`; 9999999 = Não Identificado, não a divisão 99
- Testes: `test_estoque_confere_referencia` (error), `test_territorio_sem_estoque_referencia`
  (warn). O "Não Identificado" de Sergipe é NEGATIVO no próprio painel (−3 em 202608):
  test_estoque_nao_negativo (error) exclui esse grupamento e test_estoque_nao_identificado_negativo
  (warn) o cobre — esse WARN é esperado em todo run
- O flow roda `dbt seed` e depois `dbt run --select stg_estoque_referencia path:models/marts`
- **Marco zero (F16) DESATIVADO, não excluído** (decisão do usuário, 01/10/2026): `marco-zero/`,
  `dbt/models/marco_zero_desativado/` e `dbt/tests/marco_zero_desativado/` com `enabled: false`
  (dbt_project.yml; a source no próprio yml). Sai de vez quando a F20 estiver estável. Não
  reativar sem motivo: o marco de mar/2020 ficou desatualizado com a referência 2026
- Territórios do estoque: seed `dbt/seeds/territorios.csv` (`municipio` casa com o código de 6
  dígitos, `uf` com a UF). Só os `ativo` entram (macro `efeito_no_saldo()` faz o join). Ativar
  = mudar a coluna, sem reprocessar, porque a staging já tem o estado todo. Todos os cinco ativos
  (280480, 280030, 280060, 280670 e 28), conferidos com o painel em 01/10/2026
- `ingestao_arquivos` guarda `sha256` e `bytes` do .7z (NULL nos registros anteriores à F16 parte 2)

## Fuso horário
O cron do `ingest_caged` é `"0 3 * * *"` — 3h UTC, meia-noite em Brasília.
Definido em `prefect.yaml` com `timezone: "America/Maceio"` para clareza.

## Limitação de memória — staging incremental é obrigatória, não opcional
Cada `.txt` bruto tem ~450-500MB (Brasil inteiro; filtramos ~26 mil
linhas de Sergipe; medido na F16 parte 2: pico de 405 MiB por arquivo MOV com limite de 830 MiB). Ler todas as competências de uma vez via
glob (`*.txt`) estoura memória — validado em runtime: só funcionava com
`mem_limit >= 3g`. O **servidor real de produção tem 830MB RAM total**
(~484MB disponível, ver D02) — nunca caberia processar tudo de uma vez.
Por isso a staging é `incremental`, processada uma competência por vez
pelo flow (pico de memória ~500MB, não ~3GB). **Não reverta para
`materialized='table'` com leitura via glob** sem resolver esse
dimensionamento primeiro.

## Concorrência
`prefect.yaml` limita o deployment a 1 run por vez (`ENQUEUE`). Sem isso, um run
manual sobreposto ao cron apagava o `.txt` que o outro ia processar. O
`backfill_caged` (CLI) NÃO é coberto pelo limite: não rode enquanto o flow diário
estiver ativo.

## Retenção de dados brutos
Política D06: apagar dados regeneráveis da fonte (FTP).
- `.7z` original: **deletado imediatamente** após extração bem-sucedida
  - Não será reutilizado, economia imediata (~50% espaço)
- `.txt` extraído: **deletado** ao fim de `_transformar`, só depois de staging
  + mart + `dbt test` passarem (F07 fase 2). Se algo falhar, os `.txt` ficam
  em disco para diagnóstico
- Detecção de arquivo já ingerido (`_arquivos_ingeridos`): FOR e EXC vêm da tabela
  `ingestao_arquivos` do warehouse (tipo, competência do arquivo, linhas do município), que o
  flow grava depois de cada staging. Não dá para usar "tem linha na staging": 11 arquivos EXC
  têm ZERO linhas de Socorro e seriam rebaixados todo dia. O MOV também soma as competências da
  staging (é o que valia antes do registro). Nunca o filesystem: o `.txt` some de propósito.
  Uma competência cujo dbt falhou NÃO conta como ingerida e é rebaixada na próxima execução
- FTP é fonte de verdade pública: re-download é sempre possível (minutos)

## Permissões e containers
- Container roda como usuário `caged` (UID 1000 por padrão), não root
- `docker-entrypoint.sh` roda ANTES de qualquer comando e ajusta dinamicamente
  o UID/GID de `caged` para bater com o dono real de `/data` e `/dbt` no host
  — não exige que o host use UID 1000, nem `chown` manual
- Se o bind mount acabou de ser criado pelo Docker (dono ainda `root:root`,
  primeiro `up`), o entrypoint toma posse como `caged` diretamente

## Métricas de salário
Mart publica 4 métricas de salário (todas em admissões):
1. **`salario_mediano_admissao`** (PERCENTILE_DISC)
   - Métrica de referência, robusta a outlier
   - Padrão IBGE/PDET para estudos de mercado de trabalho
2. **`salario_medio_admissao`** (AVG)
   - Para comparação, mostra divergência (indicador de concentração)
3. **`palma_index_admissao`** (razão)
   - Desigualdade: média dos top 10% ÷ média dos bottom 40%
   - Interpretação: Palma > 1.5 indica desigualdade pronunciada
4. **`admissoes_com_salario_valido`** (contagem)
   - Base do cálculo: quantos registros entraram nas métricas
   - Contexto: NULL quando nenhum registro válido

Todas filtram:
- `unidade_salario_codigo = 5` (mensal, não hora/dia/semana)
- `valor_salario_fixo > 0` (excluem "não informado")

## Boletim com IA (F19, em andamento)
docs/fatias/F19-boletim-com-ia.md e docs/boletim-ia/roteiro.md. Decidido em 29/09/2026:
- PydanticAI (não CrewAI), OpenRouter, agentes (analista, redator, revisor; advisor e Jev
  como juiz) em sequência fixa no código, com `UsageLimits` compartilhado (inclui
  `cost_limit`). Orçamento US$ 2/mês, também como limite da chave na OpenRouter
- Números nunca calculados pelo LLM: fatos por código (parte 1), cada número com id; o
  verificador de números é o `output_validator` do redator
- Sem NL2SQL: o analista só usa consultas fixas, numa cópia do warehouse `read_only`
- Análise setorial; desagregação (subgrupamento, divisão CNAE) só quando relevante;
  nunca empresa. Sem notícias nem hipóteses: o boletim descreve, não explica
- Aprovação humana antes do envio; o boletim com IA nunca sai sozinho
- Vive no produto neutro (F18); o resultado de Socorro fica na instância
- Parte 1 (fatos) feita: marts `mart_fluxo` (território × competência × grupamento ×
  subgrupamento × divisão CNAE, reconciliado), `mart_perfil_movimentacoes` (sexo, faixa
  etária), `mart_estoque_regiao` (seed `regioes.csv`: RMA) e `mart_salario_admissao` (D05,
  por território). Todos usam a regra do macro `efeito_no_saldo(colunas)` +
  `contagens_reconciliadas()`; testes conferem com mart_estoque e mart_caged_reconciliado.
  Seed `cnae_divisoes.csv` (API do IBGE); subclasse 9999999 = 'NI', não a divisão 99
- `flows/fatos.py <territorio> <competencia>`: JSON de fatos; cada número registrado com id
  em `numeros` (tabela do verificador). Limiares em `pipeline/perfis/<territorio>.toml`
  (instância), padrões em `LIMIARES_PADRAO`. Sazonalidade = faixa mín–máx do mesmo mês
- Parte 2 (proteções) feita: `flows/ia.py`. Todo agente roda por `Execucao` (context manager):
  modelos só de IA_MODELOS_PERMITIDOS e com preço de saída ≤ teto; `UsageLimits` e `RunUsage`
  compartilhados (8 requisições, 120k tokens de entrada, 20k de saída); `max_tokens`/timeout
  por papel (LIMITES_PAPEL). NÃO confiar no `cost_limit` do PydanticAI: usa genai-prices e
  não se aplica a modelo desconhecido; o custo real da OpenRouter vem em
  `provider_details['cost']`. Por isso: reserva do pior caso (limites × preço da API pública
  da OpenRouter, cache 7 dias, falha fechado) antes de rodar, e registro JSONL em
  /data/ia/custos.jsonl (reserva aberta conta pelo máximo)
- Parte 3 (agentes) feita: `flows/boletim_ia.py` (analista → redator → revisor, saídas
  Pydantic; `retries=1` em cada; pior caso 7 requisições ≤ 8) e `flows/verificador.py`
  (todo número do texto tem de estar em `numeros`, a menos de formato BR, sinal e
  arredondamento; anos e inteiros 1–12 livres; sinaliza LTDA/S.A./CNPJ). O verificador é o
  output_validator do redator: na ÚLTIMA tentativa aceita e grava situação
  `reprovado_no_verificador` para a revisão humana (não aborta). Resultado em
  /data/ia/boletins/<territorio>_<comp>/<hash[:16]>/; mesmo hash reaproveita sem LLM
  (`--refazer` força). Modelos: IA_MODELO_<PAPEL>, ou 1º permitido = redator e último =
  analista/revisor. Chave com limite VITALÍCIO na OpenRouter, reajustado à mão todo mês
  (decisão do usuário: limita perda em vazamento); 401/402/403 viram mensagem clara
- Notícias REMOVIDAS em 30/09/2026 (coletor, evidências, pesquisador, "Leituras
  relacionadas", `--com-evidencias`): o boletim usa só os fatos e os indicadores oficiais.
  Ficou do trabalho o Jev (`Execucao.decidir`, papel `juiz`, endpoint /api/alpha/decisions,
  teto 60 decisões); é sensível à redação: calibrar com casos rotulados, não por intuição.
  Preço −1 (variável) = recusado
- Parte 5 (feita): `flows/entrega_ia.py` revisar -> aprovar --por -> enviar. Rascunho só para
  `secrets/destinatarios_admin.txt`; PDF gerado UMA vez (fpdf grava data: regenerar muda os
  bytes) e o envio confere o sha256 aprovado; estado local em estado.json ao lado do resultado
  e, no envio, no envios.json do arquivo com a chave `ia-AAAAMM` (garantias da F15).
  Reprovado no verificador não vai à revisão. Nada automático
- Indicadores (`flows/indicadores.py`, anexados por padrão no boletim_ia): Pix por município
  (Olinda TransacoesPixPorMunicipio; DataBase=M devolve meses >= M, filtrar AnoMes; código
  IBGE de 7 dígitos = 6 do CAGED + dígito verificador) com leitura RELATIVA (adoção do Pix);
  Selic (SGS 432) só com Construção/Comércio em destaque; dólar fora. Cache em
  /data/ia/indicadores/; falha de rede não derruba (fica em `indicadores_ausentes`)
- 3b-2 (feita): analista levanta até 3 `duvidas`; o Jev as classifica (fora_dos_fatos/metodo/
  nenhuma; descarta "nenhuma" só com confiança >= 0,6), vendo a posição na faixa histórica e os
  gatilhos. Método -> advisor (IA_MODELO_ADVISOR, máx. 2, Orientacao tipada)
- ESCOPO FECHADO NOS FATOS (decisão do usuário, 01/10/2026): o boletim só afirma o que os fatos
  mostram, sem informação externa. Dúvida fora_dos_fatos NÃO para a geração nem pergunta a
  ninguém: vai para `fora_dos_fatos` no resultado, o redator recebe "não afirme nada sobre
  eles" e o relatório de revisão a lista. Tickets, `--responder`, `--sem-tickets` e a base de
  conhecimento local saíram (não reintroduzir). O redator lista `afirmacoes` com ids; o Jev julga cada uma (limiar 0,6); as não
  sustentadas vão ao relatório de revisão. `decisoes` = registro de decisões. request_limit 10
  (pior caso 9). Dúvidas nunca sobre empresas/estabelecimentos
- Decisões editoriais (29/09/2026): sem hipóteses (desde 30/09/2026, sem notícias, de vez);
  percentuais com 2 casas decimais
- Revisão editorial (30/09/2026): o texto interpreta, a tabela detalha. `numeros_do_texto`
  (boletim_ia) define o que o texto cita; `verificador.numeros_de_tabela` avisa repetição
  (aviso, nunca reprovação). Nota metodológica por código (`nota_metodologica`, gravada em
  resultado["boletim"]); o LLM não a escreve. Mudou prompt, não fatos: o hash é o mesmo, então
  gerar de novo exige `--refazer`
- Revisão de 01/10/2026 (diretrizes do usuário no EDITORIAL de boletim_ia.py): o texto não repete
  os cards (`CARDS`/`SO_NOS_CARDS`, `numeros_nos_cards` no prompt); panorama começa pela
  comparação com o ano anterior; "dentro da faixa" nunca é a interpretação principal; setores com
  profundidade proporcional; saldo por sexo antes da composição; regra de corte. Pix VOLTOU ao
  prompt como `sinais_da_atividade` (indicador complementar, nunca previsão nem "proxy"); meses
  de Pix posteriores ao CAGED em `pix.posteriores` (até 3, indicadores.py). PDF (pdf_analitico):
  4 páginas, atividades em destaque numa tabela única, Pix e pontos de atenção AO FINAL, texto
  justificado (paragraph align="J", também no boletim da F15), rodapé só com a marca de dados
  provisórios
