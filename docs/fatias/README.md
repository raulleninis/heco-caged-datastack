# Fatias de implementação — backlog

Cada fatia é uma unidade de trabalho **independentemente entregável**: dá para
parar depois de qualquer uma delas e o projeto continua num estado coerente.

> **Nada aqui foi aplicado ao código.** São propostas derivadas da
> [revisão de 21/09/2026](../revisao/01-sumario-executivo.md), para você decidir
> quais entram e em que ordem. As decisões que dependem de um julgamento seu
> (e não só de execução) estão em [docs/decisoes/](../decisoes/).

## Ordem sugerida

```mermaid
flowchart TD
    F01["F01 · Destravar o clone<br/>XS"] --> F02["F02 · Concluir migração<br/>DuckDB-only · M"]
    F01 --> F08["F08 · Reprodutibilidade<br/>S"]
    F02 --> F03["F03 · Agendamento real<br/>M"]
    F08 --> F03
    F03 --> F04["F04 · Religar o dbt<br/>no flow · S"]
    F04 --> F06["F06 · Janela resiliente<br/>de competências · M"]
    F02 --> F05["F05 · Corrigir salário<br/>médio · S"]
    F05 --> F09["F09 · Testes de<br/>qualidade · M"]
    F04 --> F07["F07 · Retenção do raw<br/>S"]
    F08 --> F08b["F08b · Validar com<br/>Docker real · S"]
    F09 --> F08b
    F09 --> F10["F10 · Camada analítica<br/>visível · L"]
    F06 --> F11["F11 · Observabilidade<br/>M"]
    F09 --> F12["F12 · FOR/EXC +<br/>reconciliação · L"]
    F11 --> F13["F13 · Migração<br/>para nuvem · L"]
    F10 --> F14["F14 · Narrativa do<br/>repositório · M"]
    F04 --> F15["F15 · Entrega por e-mail<br/>e arquivo autenticado · L"]
    F06 --> F15
    F12 --> F16["F16 · Estoque a partir<br/>do marco zero · L"]
    F11 --> F17["F17 · Teste de<br/>silêncio · XS"]

    classDef agora fill:#fde8e8,stroke:#c0392b,color:#7b241c
    classDef pre fill:#fef5e7,stroke:#b9770e,color:#7e5109
    classDef prod fill:#eaf2f8,stroke:#2874a6,color:#1b4f72
    classDef vitrine fill:#eafaf1,stroke:#1e8449,color:#145a32
    class F01,F02,F03,F04,F05 agora
    class F06,F07,F08,F08b,F09 pre
    class F11,F12,F13,F15,F16,F17 prod
    class F10,F14 vitrine
```

## Tabela

| # | Fatia | Esforço | Fase | Achados que resolve | Depende de |
|---|---|---|---|---|---|
| [F01](F01-destravar-o-clone.md) | Destravar o clone | XS | agora | M | — |
| [F02](F02-concluir-migracao-duckdb.md) | Concluir a migração DuckDB-only | M | agora | A, N | F01 |
| [F03](F03-agendamento-real.md) | Fazer o agendamento existir | M | agora | B, C, I | F02, F08 |
| [F04](F04-religar-dbt-no-flow.md) | Religar o dbt no flow | S | agora | (run_dbt comentado) | F03 |
| [F05](F05-corrigir-salario-medio.md) | Corrigir `salario_medio_admissao` | S | agora | D | F02 |
| [F06](F06-janela-resiliente.md) | Janela resiliente de competências | M | pré-prod | E | F04 |
| [F07](F07-retencao-e-permissoes.md) ✅ | Retenção do raw + não-root | S | pré-prod | G, I | F04 |
| [F08](F08-reprodutibilidade.md) | Reprodutibilidade do ambiente | S | pré-prod | J, K, L | F01 |
| [F08b](F08b-validar-reprodutibilidade-docker.md) ✅ | Validar com Docker real (F08 + F09 + revisão) | S | pré-prod | — | F08, F09 |
| [F09](F09-testes-de-qualidade.md) | Testes de qualidade ampliados | M | pré-prod | D, F | F05 |
| [F10](F10-camada-analitica.md) | Camada analítica visível | L | vitrine | (portfólio) | F09 |
| [F11](F11-observabilidade.md) ✅ | Observabilidade e alerta | M | produção | B | F06 |
| [F12](F12-for-exc-reconciliacao.md) 🟡 | Ingestão FOR/EXC + reconciliação | L | produção | H | F09 |
| [F13](F13-migracao-nuvem.md) | Migração para nuvem | L | produção | — | F11 |
| [F14](F14-narrativa-do-repositorio.md) | Narrativa do repositório | M | vitrine | (portfólio) | F10 |
| [F15](F15-entrega-por-email-e-arquivo.md) ✅ | Entrega por e-mail e arquivo autenticado | L | produção | (objetivo de produção) | F04, F06 |
| [F16](F16-estoque-a-partir-do-marco-zero.md) | Estoque a partir do marco zero | L | produção | (D11) | F12, F09 |
| [F17](F17-teste-de-silencio.md) ✅ | Teste de silêncio: provar que o alerta chega | XS (+ espera) | produção | (validação de F11) | F11 |

## Se você só tiver um fim de semana

`F01 → F02 → F05 → F04` já produz o maior salto: o projeto passa a **subir num
clone limpo**, a ter **uma única arquitetura coerente com a documentação**, e a
entregar **um número que não está errado**.

## Legenda de esforço

| | |
|---|---|
| **XS** | menos de 15 min |
| **S** | menos de 1 h |
| **M** | meio dia |
| **L** | 1 a 3 dias |
| **XL** | mais que isso |
