# Decisões

Estas são as escolhas que **dependem de um julgamento seu** — não de execução.
Cada fatia em [docs/fatias/](../fatias/) que depende de uma delas está marcada.

> Formato: cada arquivo apresenta o contexto, as opções com seus trade-offs reais,
> uma **recomendação** — que é uma sugestão, não uma conclusão — e, depois de decidida,
> o registro da **Decisão**: data, escolha, porquê e o que muda em relação ao estado
> anterior. Isso é exatamente o tipo de documento que um entrevistador gosta de ver,
> porque mostra *como* você pensa, não só o que você escolheu.

| # | Decisão | Bloqueia | Escolha | Status |
|---|---|---|---|---|
| [D01](D01-duckdb-only-ou-postgres.md) | DuckDB-only ou manter Postgres? | [F02](../fatias/F02-concluir-migracao-duckdb.md) | DuckDB-only | decidida · 21/09/2026 |
| [D02](D02-modelo-de-execucao.md) | Modelo de execução na nuvem | [F03](../fatias/F03-agendamento-real.md), [F13](../fatias/F13-migracao-nuvem.md) | A — VM existente, Docker Compose | decidida · 21/09/2026 |
| [D03](D03-onde-guardar-os-dados.md) | Onde vivem o warehouse e o raw | [F13](../fatias/F13-migracao-nuvem.md) | disco da VM, sem backup | decidida · 21/09/2026 |
| [D04](D04-politica-de-falha-de-teste.md) | Teste dbt falhando derruba o flow? | [F04](../fatias/F04-religar-dbt-no-flow.md) | C — severidade por teste | decidida · 21/09/2026 |
| [D05](D05-metrica-de-salario.md) | Qual métrica de salário publicar | [F05](../fatias/F05-corrigir-salario-medio.md) | mediana + média, só mensal, sem zero | decidida · 21/09/2026 |
| [D06](D06-retencao-de-dados-brutos.md) | Política de retenção do raw | [F07](../fatias/F07-retencao-e-permissoes.md) | A agora, B depois da F09 | decidida · 21/09/2026 |
| [D07](D07-repositorio-publico.md) | Quando abrir o repositório | [F10](../fatias/F10-camada-analitica.md) | após F01+F02+F05 | decidida · 21/09/2026 |
| [D08](D08-gestao-de-segredos.md) | Gestão de segredos | [F13](../fatias/F13-migracao-nuvem.md) | `.env` 600, escopo mínimo | decidida · 21/09/2026 |
| [D09](D09-claude-md-na-vitrine.md) | O que fazer com o CLAUDE.MD | [F14](../fatias/F14-narrativa-do-repositorio.md) | D com A como acabamento | decidida · 21/09/2026 |
| [D10](D10-escopo-analitico.md) | Escopo analítico do projeto | [F10](../fatias/F10-camada-analitica.md) | B + C ancoradas por D | decidida · 21/09/2026 |
| [D11](D11-estoque-de-emprego.md) | Como constituir o estoque de emprego | [F16](../fatias/F16-estoque-a-partir-do-marco-zero.md), [F10](../fatias/F10-camada-analitica.md) | marco zero manual (31/12/2019) por município × grupamento + movimentações MOV/FOR/EXC | decidida · revisada 22/09/2026 (pontos abertos) |

## Pontos que continuam abertos dentro de decisões já tomadas

| Onde | O quê |
|---|---|
| [D10](D10-escopo-analitico.md) | qual é a **pergunta de negócio** específica (a "D" do escopo) |
| [D07](D07-repositorio-publico.md) | versionar amostra do recorte ou só o mart agregado; termos de uso do PDET |
| [F15](../fatias/F15-entrega-por-email-e-arquivo.md) | **provedor de e-mail** |
| [D03](D03-onde-guardar-os-dados.md) | se o FTP do PDET mantém o histórico necessário para reconstruir o warehouse |
| [D11](D11-estoque-de-emprego.md) | valor e fonte do marco zero de Socorro; marcos zero de Aracaju e Sergipe (depois, sem bloquear) |
