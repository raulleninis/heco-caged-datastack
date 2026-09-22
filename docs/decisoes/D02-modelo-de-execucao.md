# D02 · Modelo de execução na nuvem

**Status:** decidida (21/09/2026) · **Bloqueia:** [F03](../fatias/F03-agendamento-real.md), [F13](../fatias/F13-migracao-nuvem.md) · **Urgência:** média

## Contexto — o dimensionamento honesto

| | |
|---|---|
| Dado novo | **1 vez por mês** |
| Duração de um run | minutos |
| Consumidores persistentes | **zero** |
| Motivo do cron diário | a data de publicação do PDET é imprevisível — não há trabalho diário |

Uma VM 24/7 fica ociosa **99,9% do tempo**.

## Opções

### A. VM pequena 24/7 com Docker Compose (o caminho "óbvio")

| ✅ | O `docker-compose.yml` atual quase funciona como está |
| ✅ | Prefect Server com UI — bom de mostrar em entrevista |
| ✅ | Tailscale roda igual; o desenho de rede atual continua válido |
| ❌ | Custo contínuo para trabalho de minutos/mês |
| ❌ | VM é bicho de estimação: atualização de SO, disco, monitoramento |

### B. Prefect Cloud (free tier) + worker efêmero ✅ recomendada

| ✅ | Sem servidor para manter; o free tier cobre 1 flow mensal com folga |
| ✅ | Mantém "Prefect" no currículo — e o uso fica mais próximo do que empresa faz |
| ✅ | Custo próximo de zero |
| ⚠️ | Dependência de SaaS externo; exige repensar onde o worker roda |
| ⚠️ | O warehouse **precisa** viver fora do compute efêmero ([D03](D03-onde-guardar-os-dados.md)) |

### C. GitHub Actions com `schedule`

| ✅ | Zero infraestrutura; o repositório *é* o deploy |
| ✅ | CI/CD e execução no mesmo lugar; logs públicos viram vitrine |
| ✅ | Gratuito em repositório público |
| ❌ | **Perde o Prefect** — e com ele um item de currículo |
| ❌ | Runner tem disco efêmero e limite de tempo: 450 MB de download cabe, mas é apertado |
| ⚠️ | `schedule` do Actions tem atraso e pode ser desabilitado por inatividade |

### D. Container agendado no provedor (Cloud Run Jobs, ACI, Fargate)

| ✅ | Paga-se o que roda; o `Dockerfile` atual serve |
| ✅ | Sem servidor, sem VM de estimação |
| ⚠️ | Amarra ao provedor; exige object storage para o warehouse |

## A tensão central

**Execução efêmera é barata, mas não combina com Prefect Server**, que é processo
longo com banco próprio. Ou você mantém um servidor (A), ou tira o servidor da
equação (B), ou tira o Prefect (C/D).

Não há resposta universal — o peso depende de quanto "Prefect" importa para as vagas
que você mira. **Essa é a pergunta de arquitetura que um entrevistador vai fazer**,
então a resposta registrada aqui vale por si.

## Recomendação

**Opção B**, com **C como plano de contingência**.

B preserva o Prefect (que já está no projeto e no currículo), elimina o custo do
servidor, e força a separação entre compute e estado — que é justamente a disciplina
que a nuvem exige e o desenho atual não tem.

Se a complexidade de B incomodar, C é uma queda suave: mais simples, mais barata,
custa um item de currículo.

> **Nota sobre a [F03](../fatias/F03-agendamento-real.md):** ela pode ser feita hoje
> no servidor caseiro com `.serve()`, sem esperar esta decisão. Mas se a escolha for B
> ou D, o padrão **worker + work pool** é mais próximo do destino — e evita refazer.

## Decisão

> **Data:** 21/09/2026
> **Escolha:** **A** — VM 24/7 com Docker Compose, no servidor Oracle que já existe.
> Mantém a estrutura atual (Prefect Server + `.serve()`).
> **Porquê:** o servidor já estará ligado de qualquer modo, então o custo marginal é
> zero e a premissa "VM ociosa 99,9%" deixa de pesar. B, C e D trocariam um custo
> inexistente por complexidade.

### O que muda em relação ao que o doc recomendava

| | Antes | Depois |
|---|---|---|
| Recomendação do doc | B (Prefect Cloud + worker efêmero), C como contingência | **A** |
| [F03](../fatias/F03-agendamento-real.md) | worker + work pool sugerido "se a escolha for B ou D" | `.serve()` basta |
| Tailscale em produção | assumido pelo desenho de rede | **não necessário**: portas em `127.0.0.1`, UI por túnel SSH (a saída do projeto é e-mail, ver [F15](../fatias/F15-entrega-por-email-e-arquivo.md)) |

### Ressalvas (medidas na VM, 21/09/2026)

- **RAM: 830 MiB, ~484 disponíveis, 302 MiB de swap já em uso**, dividida com o
  `observia` (uvicorn, ~150 MiB, quase todo em swap). Stack em repouso estimado em
  700–800 MiB. Não é OOM (há 1,3 GiB de swap livre), é lentidão.
- Mitigação: [F02](../fatias/F02-concluir-migracao-duckdb.md) (sem Postgres/Adminer),
  `mem_limit` compatíveis com 830 MiB, e **medir um run completo** com `docker stats`.
- **Contingência:** se a medição mostrar que o `observia` ou o pipeline sofrem, tirar o
  servidor da RAM (Prefect Cloud ou Actions — as opções B/C acima).
