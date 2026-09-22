# F10 · Camada analítica visível

| | |
|---|---|
| **Esforço** | L (1 a 3 dias) |
| **Fase** | vitrine |
| **Depende de** | [F09](F09-testes-de-qualidade.md) |
| **Objetivo** | Fazer o projeto demonstrar competência de **analista de dados**, não só de infraestrutura |

## Problema

Você disse que o projeto é vitrine para **vagas de analista de dados**. Hoje o
repositório demonstra, em ordem de destaque: Docker, Prefect, dbt, DuckDB, FTP,
py7zr — e, por último, **uma única agregação** (`group by competencia, grupamento`).

O projeto **grita "infraestrutura" e sussurra "análise"**.

E há um problema mais duro: **não há saída visível**. Um avaliador que abre o repo vê
um `README` descrevendo um pipeline, mas não vê **nenhum número, nenhum gráfico,
nenhuma conclusão** sobre o mercado de trabalho de Nossa Senhora do Socorro.

Para rodar e ver algo, ele precisaria: clonar, criar `.env` (que não existe), subir a
stack, esperar o download de 450 MB do FTP do Ministério, e rodar o dbt. **Ninguém faz isso.**

Enquanto isso, os dados que você já tem contam uma história boa:

| competência | saldo total |
|---|---|
| 202601 | −138 |
| 202602 | −6 |
| 202603 | **+179** |
| 202604 | −143 |
| 202605 | −42 |

Serviços oscila de **+117 (mar)** para **−196 (abr)**. Construção sai de −10 (jan)
para **+46 (mai)**. Isso é material de análise — e está invisível.

## Escopo

### 1. Amostra versionada (o desbloqueio)

Um `.csv` ou `.parquet` **pequeno** (só o recorte do município, ~1.500 linhas/mês,
poucos MB) commitado no repositório, mais um `dbt seed` ou caminho alternativo que
permita rodar o pipeline **sem FTP e sem 2,5 GB**.

É a diferença entre "dá pra entender lendo" e "dá pra rodar em 2 minutos".
Cheque a licença dos microdados do PDET antes de redistribuir — ver
[D07](../decisoes/D07-repositorio-publico.md).

### 2. Modelos analíticos de verdade

O grupamento por seção é um começo. O que uma vaga de analista espera ver:

- **série temporal com média móvel** e comparação ano-a-ano;
- **recorte demográfico** — sexo, raça/cor, faixa etária, grau de instrução
  (as colunas já estão na staging e **nenhuma é usada**);
- **top ocupações (CBO)** por admissão e desligamento;
- **distribuição salarial** — mediana, quartis, não só média (ver [F05](F05-corrigir-salario-medio.md));
- **rotatividade** por grupamento (admissões+desligamentos sobre estoque);
- comparação com **Aracaju** ou com o total de **SE**, para dar escala ao número.

> A staging já carrega `sexo`, `raca_cor`, `idade`, `grau_de_instrucao`,
> `cbo_2002_ocupacao`, `tam_estab_jan` — 28 colunas. O mart usa **duas**.
> O dado mais interessante do projeto está ingerido e parado.

### 3. Saída visível no README

Ao menos um gráfico versionado (PNG/SVG) e uma tabela de destaque, gerados por
script reproduzível — não colados à mão.

### 4. Um artefato de análise

Notebook ou `.md` com achados: o que os dados dizem sobre o mercado de trabalho de
N. Sra. do Socorro. **Esse é o artefato que vende você numa vaga de analista** —
mais que o `docker-compose.yml`.

## Relação com o CrewAI

O `CLAUDE.MD` planeja relatório em PDF via CrewAI. Esta fatia é **pré-requisito**:
o agente redator precisa de fatos calculados deterministicamente para escrever em cima.
A regra que você já definiu — *"números nunca calculados pelo LLM"* — está certa, e
esta fatia é quem produz esses números.

Ordem correta: **análise primeiro, LLM depois.** Um relatório automatizado sobre uma
única agregação não impressiona; sobre uma camada analítica rica, impressiona muito.

## Critério de aceite

Um avaliador consegue, em **menos de 5 minutos e sem acesso ao FTP**:

```bash
git clone <repo> && cd <repo>
cp .env.example .env
docker compose up -d
make demo     # ou equivalente
```

e ver números e ao menos um gráfico. E o `README` mostra um resultado **antes** de
explicar a arquitetura.
