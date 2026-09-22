# Revisão geral — sumário executivo

**Projeto:** CAGED Analytics — Nossa Senhora do Socorro/SE
**Data:** 21/09/2026
**Escopo:** revisão completa da versão preliminar, com vistas a (a) produção em
servidor nuvem e (b) uso do repositório como vitrine profissional para vagas de dados.

> **Nenhuma alteração foi feita no código do projeto.** Esta revisão produz apenas
> documentos: achados, [fatias de implementação](../fatias/) e
> [decisões em aberto](../decisoes/), para você decidir o que entra e em que ordem.

---

## Veredito em um parágrafo

O projeto tem **fundação boa e execução interrompida**. As escolhas de arquitetura são
defensáveis, os diagramas do README são acima da média, e a nota sobre a consolidação
`MOV`/`FOR`/`EXC` demonstra domínio real da fonte — algo raro em projeto de portfólio.
Mas o pipeline **não roda desde 28 de julho**, o agendamento **nunca existiu**, a
migração para DuckDB **está pela metade enquanto a documentação a declara concluída**,
e a principal métrica de negócio — salário médio — **está publicando um número errado**.
São todos problemas de conclusão, não de concepção.

---

## Os 5 achados que importam

### 1. 🔴 O pipeline não roda há ~2 meses, e nada avisou

Zero deployments no Prefect. O único flow run da história foi um backfill **manual** em
28/07/2026. O `.serve(cron=...)` está preso dentro de `if __name__ == "__main__"`, o
`Dockerfile` não tem `CMD`, e o container `pipeline` **sequer existe**.

Consequência: o FTP já publicou até **202607**; o projeto tem até **202605**.

→ [evidência E4](03-evidencias.md#e4-o-agendamento-nunca-existiu) · [F03](../fatias/F03-agendamento-real.md), [F11](../fatias/F11-observabilidade.md)

### 2. 🔴 A métrica principal está errada — não imprecisa, errada

`salario_medio_admissao` mistura unidades de salário. Um único registro com unidade
**hora** e valor de R$ 356.620,00 inflou a média de Construção/202603 em **268%**
(R$ 7.265,68 contra ~R$ 1.900 nos meses vizinhos). A aritmética fecha exatamente.

Os 6 testes dbt existentes **não pegaram** — nenhum olha para valor.

→ [evidência E6](03-evidencias.md#e6-salario_medio_admissao-está-errado--mistura-unidades-de-salário) · [F05](../fatias/F05-corrigir-salario-medio.md), [D05](../decisoes/D05-metrica-de-salario.md)

### 3. 🔴 Um clone limpo não sobe

O README manda `cp .env.example .env`. **Esse arquivo não existe.** Sem ele,
`POSTGRES_PASSWORD` fica vazio, o Postgres se recusa a inicializar, e como os demais
serviços dependem dele via `service_healthy`, **a stack inteira não sobe**.

Para um projeto-vitrine, é o pior lugar possível para falhar: é o primeiro comando
que um avaliador digita.

→ [evidência E3](03-evidencias.md#e3-clone-limpo--docker-compose-up--d-falha) · [F01](../fatias/F01-destravar-o-clone.md)

### 4. 🟠 A migração DuckDB está pela metade, documentada como concluída

O mart vive no **Postgres** (`main_public.mart_caged_mensal_grupamento`); o `.duckdb`
tem 274 KB com apenas uma view; e o projeto dbt **não faz nem `parse`** sem
`POSTGRES_HOST`. Enquanto isso o `CLAUDE.MD` afirma no passado que *"Postgres e
Metabase foram removidos"*, e o README marca `[x]` a remoção — e `[ ]` a consolidação,
na linha seguinte.

A direção está certa; o problema é o **registro**. Numa entrevista, *"cadê o Postgres
que você diz ter removido?"* não é pergunta técnica — é pergunta sobre confiabilidade
do que você afirma.

→ [evidências E1](03-evidencias.md#e1-o-mart-não-está-no-duckdb--está-no-postgres) e [E2](03-evidencias.md#e2-o-projeto-dbt-não-faz-parse-sem-postgres) · [F02](../fatias/F02-concluir-migracao-duckdb.md), [D01](../decisoes/D01-duckdb-only-ou-postgres.md)

### 5. 🟠 Competências publicadas são perdidas para sempre

`competencia_alvo()` devolve **sempre e apenas o mês anterior**. Se a competência não
estiver no FTP naquele mês, o flow desiste — e quando o mês vira, **nunca mais pergunta
por ela**. 202606 e 202607 estão disponíveis e são inalcançáveis pelo flow diário.

A premissa de fundo está errada: o `CLAUDE.MD` diz defasagem de "1 mês"; a real é de
**1,5 a 2 meses**. Uma janela de 1 mês é incompatível com essa fonte.

→ [evidência E7](03-evidencias.md#e7-defasagem-de-2-competências--bug-de-janela) · [F06](../fatias/F06-janela-resiliente.md)

---

## O achado que não é um defeito

Você disse que o projeto é vitrine para **vagas de analista de dados**. Hoje ele
demonstra, em ordem de destaque: Docker, Prefect, dbt, DuckDB, FTP — e, por último,
**uma única agregação**.

A staging carrega **28 colunas** (`sexo`, `raca_cor`, `idade`, `grau_de_instrucao`,
`cbo_2002_ocupacao`…). O mart usa **duas**. O dado mais interessante do projeto já está
ingerido e parado.

Somado a isso: **não há saída visível**. Nenhum número, nenhum gráfico, nenhuma
conclusão sobre o mercado de trabalho de N. Sra. do Socorro — e para ver algo, o
avaliador precisaria subir a stack e baixar 450 MB do FTP do Ministério. Ninguém faz isso.

**O projeto grita "infraestrutura" e sussurra "análise".** Para a vaga que você mira,
está otimizado na dimensão errada.

→ [F10](../fatias/F10-camada-analitica.md), [F14](../fatias/F14-narrativa-do-repositorio.md), [D10](../decisoes/D10-escopo-analitico.md)

---

## O que já está bom — não mexa

- **Os diagramas mermaid** (arquitetura e ERD) são melhores que a média do mercado.
- **A nota sobre consolidação `MOV`/`FOR`/`EXC`** demonstra domínio da fonte e
  honestidade sobre limitação — sinal de senioridade.
- **O `.gitignore`** foi bem feito desde o primeiro commit: `.env` **nunca** entrou no
  histórico (verificado), `data/` e `dbt/logs/` ignorados. Não há vazamento a remediar.
- **A restrição de concorrência do DuckDB** está documentada corretamente no `CLAUDE.MD` —
  inclusive antes de ela virar problema.
- **O recorte geográfico específico.** "Mercado de trabalho de Nossa Senhora do Socorro"
  é muito mais memorável que "análise de dados do CAGED". É uma força, não uma limitação.
- **A regra de design do CrewAI** — *"números nunca calculados pelo LLM"* — está certa,
  e muita gente sênior erra isso.

---

## Ordem recomendada

Se você só tiver **um fim de semana**:

```
F01 → F02 → F05 → F04
```

Isso já produz o maior salto: o projeto passa a **subir num clone limpo**, a ter **uma
arquitetura coerente com a própria documentação**, e a publicar **um número que não
está errado**.

Se tiver **mais tempo**, o maior retorno para o objetivo de currículo não é a nuvem —
é [F10](../fatias/F10-camada-analitica.md) e [F14](../fatias/F14-narrativa-do-repositorio.md).
Um recrutador avalia o **README e o código**; a VM ele não vê.

---

## Mapa dos documentos

| | |
|---|---|
| [02-achados.md](02-achados.md) | Todos os achados, por dimensão, com severidade |
| [03-evidencias.md](03-evidencias.md) | Como reproduzir cada achado — comandos e saídas reais |
| [docs/fatias/](../fatias/) | 14 fatias de implementação, independentemente entregáveis |
| [docs/decisoes/](../decisoes/) | 10 decisões em aberto, com trade-offs e recomendação |
