# CAGED Analytics — Nossa Senhora do Socorro/SE

Pipeline de dados educacional que ingere, transforma e (em breve) resume
automaticamente os microdados do **Novo CAGED** (PDET / Ministério do
Trabalho e Emprego), com recorte geográfico fixo em Nossa Senhora do
Socorro/SE, rodando inteiramente num servidor caseiro headless.

## Arquitetura do pipeline

```mermaid
flowchart LR
    FTP[("FTP público\nftp.mtps.gov.br")]
    SCAN["Prefect\ncompetencias_faltantes<br/>últimos 6 meses"]
    DL["baixar_arquivo()<br/>+ extrair_7z()"]
    DEL["deletar .7z<br/>(liberando espaço)"]
    RAW[("/data/raw/extraido<br/>.txt")]
    RUN["dbt run<br/>+ dbt test"]
    MART["mart_caged_mensal_grupamento<br/>(table, DuckDB)<br/>mediana, média, Palma Index"]
    REPORT["CrewAI + PDF<br/>(planejado)"]

    FTP -->|"varre<br/>lacunas"| SCAN
    SCAN -->|"competências<br/>faltantes"| DL
    DL -->|"extrai"| RAW
    RAW -->|"delete<br/>.7z"| DEL
    RAW -->|"source declarado<br/>(all_varchar)"| RUN
    RUN -->|"materializa<br/>staging (table)"| MART
    MART -.->|"próxima fase"| REPORT
```

## Estrutura dos dados

```mermaid
erDiagram
    stg_caged_movimentacoes {
        bigint competencia_mov
        bigint regiao
        bigint uf
        bigint municipio
        varchar secao
        bigint subclasse
        bigint saldo_movimentacao
        bigint cbo_2002_ocupacao
        bigint categoria
        bigint grau_de_instrucao
        bigint idade
        double horas_contratuais
        bigint raca_cor
        bigint sexo
        bigint tipo_empregador
        bigint tipo_estabelecimento
        bigint tipo_movimentacao
        bigint tipo_de_deficiencia
        bigint ind_trab_intermitente
        bigint ind_trab_parcial
        double salario
        bigint tam_estab_jan
        bigint indicador_aprendiz
        bigint origem_da_informacao
        bigint competencia_dec
        bigint indicador_de_fora_do_prazo
        bigint unidade_salario_codigo
        double valor_salario_fixo
        varchar grupamento
        varchar subgrupamento
    }

    mart_caged_mensal_grupamento {
        bigint competencia_mov
        varchar grupamento
        bigint admissoes
        bigint desligamentos
        bigint saldo_liquido
        bigint admissoes_com_salario_valido
        double salario_mediano_admissao
        double salario_medio_admissao
        double palma_index_admissao
    }

    stg_caged_movimentacoes ||--o{ mart_caged_mensal_grupamento : "agregada em"
```

`saldo_movimentacao` assume só dois valores: `1` (admissão) ou `-1`
(desligamento) — é a partir dele que `admissoes`, `desligamentos` e
`saldo_liquido` são calculados na mart. `grupamento` é derivado de `secao`
(A=Agropecuária, B-E=Indústria, F=Construção, G=Comércio, H-U=Serviços).

## Stack

| Camada | Ferramenta |
|---|---|
| SO | Ubuntu Server 24.04 LTS (headless) |
| Acesso remoto | SSH (chave) + Tailscale (sem port forwarding) |
| Containers | Docker + Docker Compose |
| Armazenamento e transformação | DuckDB + dbt-core / dbt-duckdb |
| Orquestração | Prefect 3.x |
| Fonte de dado | PDET/Novo CAGED (FTP, `.7z`, mensal, 1 mês de defasagem) |

## Como rodar

```bash
cp .env.example .env
docker compose up -d
docker compose run --rm pipeline dbt run --project-dir /dbt --profiles-dir /dbt
docker compose run --rm pipeline dbt test --project-dir /dbt --profiles-dir /dbt
```

Todas as variáveis têm valores padrão. `PREFECT_HOST` só precisa ser editada se você
acessa a UI do Prefect por outra máquina via Tailscale — sem ele, o padrão é
`localhost` e o clone sobe sem Tailscale.

O container `pipeline` roda contínuo: ao subir, aplica o deployment declarado em `prefect.yaml`
(`prefect deploy --all`) e inicia um worker (`prefect worker start --pool default`) que consome
o schedule cron diário às 3h UTC (meia-noite em Brasília).

Backfill manual de um ano inteiro:
```bash
docker compose run --rm pipeline python flows/ingest_caged.py backfill 2026
```

### Permissões

O container ajusta automaticamente o UID/GID do processo para bater com o dono de `data/`
e `dbt/` no host (ver `pipeline/docker-entrypoint.sh`) — não é necessário `chown` manual,
mesmo que o usuário do host não seja UID 1000.

### Limpeza de dados

Arquivos baixados do FTP são armazenados em `data/raw/`. O pipeline **automaticamente deleta
os `.7z` originais após extração**, conservando os `.txt` extraídos. A staging já materializa
como `table` (F09) — o `.txt` ainda não é deletado (isso é a fase 2 de F07, pendente), mas
a staging não depende mais dele após o primeiro `dbt run`.

## Estrutura do repositório

```
.
├── docker-compose.yml
├── pipeline/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── docker-entrypoint.sh
│   ├── start.sh
│   ├── prefect.yaml
│   └── flows/ingest_caged.py
└── dbt/
    ├── dbt_project.yml
    ├── profiles.yml
    ├── tests/
    │   ├── test_unicidade_grao_mart.sql
    │   ├── test_coerencia_saldo_liquido.sql
    │   └── test_faixa_salario_plausivel.sql
    └── models/
        ├── staging/
        │   ├── stg_caged_movimentacoes.sql
        │   └── _sources.yml
        └── marts/mart_caged_mensal_grupamento.sql
```

## Nota sobre a consolidação do Novo CAGED

Cada competência de **movimentação** (o mês em que a admissão/desligamento
de fato ocorreu) é publicada em três arquivos separados, organizados pela
competência de **declaração**:

- `CAGEDMOVAAAAMM` — movimentações declaradas **dentro do prazo**
- `CAGEDFORAAAAMM` — movimentações declaradas **fora do prazo**
- `CAGEDEXCAAAAMM` — declarações anteriores que foram **excluídas/retificadas**

O pipeline atual ingere **só o `CAGEDMOV`** — ou seja, o saldo calculado hoje
reflete apenas o que foi declarado dentro do prazo, e tende a subestimar
levemente o valor real de competências recentes. Para chegar ao número
definitivo de uma competência de movimentação, é preciso, nos meses
seguintes, somar as declarações fora do prazo e subtrair as exclusões
referentes a ela — isso ainda não está implementado (ver Roadmap).

## Roadmap

- [x] Ingestão automatizada (FTP → `.7z` → `.txt`)
- [x] Transformação e testes de qualidade (dbt + DuckDB)
- [x] Agendamento via Prefect
- [x] Simplificação da arquitetura: remoção do Postgres e do Metabase — DuckDB passa a ser a única camada de dado
- [x] Ajustes finais de consolidação da migração (revisão de materializações, configs e testes do dbt já 100% DuckDB)
- [ ] Ingestão de `CAGEDFORAAAAMM` (fora do prazo) e `CAGEDEXCAAAAMM` (exclusões)
- [ ] Modelo de reconciliação: mart que combina movimentações + fora do prazo − exclusões, por competência de movimentação
- [ ] Relatório mensal em PDF via CrewAI
  - [ ] Configuração do CrewAI e definição dos agentes (Analista de Dados, Pesquisador de Contexto, Redator, Revisor)
  - [ ] Integração via OpenRouter (modelo a definir)
  - [ ] Criação do layout/template visual do relatório (PDF)
  - [ ] Geração determinística dos fatos (SQL) → narrativa (LLM) → renderização (PDF)