# F14 · Narrativa do repositório

| | |
|---|---|
| **Esforço** | M (meio dia) |
| **Fase** | vitrine |
| **Depende de** | [F10](F10-camada-analitica.md) |
| **Objetivo** | Fazer o repositório contar a história certa em 5 minutos de leitura |

## O cenário real de avaliação

Alguém abre seu GitHub vindo do LinkedIn. Tem **5 minutos**. Lê o README, olha a
estrutura de pastas, dá uma passada no histórico de commits. Não clona, não roda.

O que essa pessoa encontra hoje:

### 1. Um commit só

```
ee8f216 Estrutura inicial: postgres, prefect, pipeline dbt+duckdb para CAGED
 12 files changed, 416 insertions(+)
```

Um único commit apaga **toda a narrativa de engenharia**. Não há evidência de como
você pensa, itera, corrige. Pior: a mensagem diz *"postgres"*, enquanto o README diz
que o Postgres foi removido — o histórico **contradiz** a documentação.

> **Não reescreva a história.** O custo de um `git rebase` aqui supera o ganho.
> O que importa é daqui pra frente: cada fatia deste backlog é um commit (ou uma PR)
> com mensagem que explica **por quê**, não o quê. Vinte commits bem escritos nos
> próximos dois meses valem mais que um histórico fabricado.

### 2. README que promete o que o código não entrega

Já coberto na [F02](F02-concluir-migracao-duckdb.md), mas o impacto aqui é diferente:
numa entrevista, *"cadê o Postgres que você diz ter removido?"* não é uma pergunta
técnica — é uma pergunta sobre **confiabilidade do que você afirma**. É o dano mais
caro de todos os achados desta revisão, e o mais barato de consertar.

O mesmo vale para `[x] Agendamento via Prefect` com zero deployments
([evidência E4](../revisao/03-evidencias.md#e4-o-agendamento-nunca-existiu)).

### 3. CLAUDE.MD na raiz

O arquivo é um contexto para agentes de IA — mas fica na **raiz**, com nome em caixa
alta, ao lado do README. Um recrutador vai abrir. Dois riscos:

- ele revela que o projeto é assistido por IA de um jeito que você não escolheu como
  apresentar (isso é normal hoje — mas a **forma** de comunicar deveria ser sua decisão);
- ele contém afirmações desatualizadas (Postgres removido, defasagem de 1 mês) que
  se tornam **uma segunda fonte de incoerência** para manter.

Opções: mover para `.claude/CLAUDE.md`, ou assumi-lo como parte da narrativa
("como eu uso IA no meu fluxo"). Decisão em [D09](../decisoes/D09-claude-md-na-vitrine.md).

> Nota técnica: o nome versionado é `CLAUDE.MD` (extensão em caixa alta). Em Linux o
> carregamento automático é sensível a caixa — confira se o arquivo está sendo lido.

### 4. Sem LICENSE

Repositório sem licença é, por padrão, "todos os direitos reservados". Para portfólio,
é fricção gratuita.

## Escopo

1. **README reordenado**: resultado primeiro, arquitetura depois. Hoje ele abre com
   um `flowchart` de ferramentas. Deveria abrir com **um gráfico e uma frase sobre o
   mercado de trabalho de N. Sra. do Socorro** — a pergunta que o projeto responde.
2. Reconciliar todas as afirmações com a realidade (Roadmap, stack, comandos).
3. Seção **"Decisões técnicas"** — por que DuckDB, por que remover Postgres, por que
   dbt. O `CLAUDE.MD` tem esse raciocínio e o README não. Linkar para
   [docs/decisoes/](../decisoes/) é meio caminho andado.
4. Seção **"Limitações conhecidas"** — a nota sobre `CAGEDMOV` já está lá e é
   excelente. Expandir. Admitir limitação é sinal de senioridade.
5. `LICENSE` (MIT resolve).
6. Screenshot ou gráfico versionado no topo.
7. Daqui pra frente: **um commit por fatia**, mensagem explicando o porquê.

## O que já está bom — não mexa

- Os **diagramas mermaid** de arquitetura e ERD. São melhores que a média do mercado.
- A **nota sobre consolidação do CAGED** (`MOV`/`FOR`/`EXC`). Demonstra domínio real
  da fonte, que é raro em projeto de portfólio.
- O recorte geográfico específico. "Mercado de trabalho de Nossa Senhora do Socorro"
  é muito mais memorável que "análise de dados do CAGED".

## Critério de aceite

O teste dos 5 minutos, com alguém de fora:

> Abra o repositório. Sem rodar nada, me diga: **o que este projeto faz, que pergunta
> ele responde, e qual foi a resposta?**

Se a pessoa não conseguir responder as três, o README ainda não está pronto.
