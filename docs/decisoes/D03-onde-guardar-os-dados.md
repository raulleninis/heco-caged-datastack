# D03 · Onde vivem o warehouse e o raw

**Status:** decidida (21/09/2026) · **Bloqueia:** [F13](../fatias/F13-migracao-nuvem.md) · **Urgência:** média

## Contexto

Dois artefatos com necessidades opostas:

| | tamanho | precisa sobreviver? |
|---|---|---|
| `data/warehouse/caged.duckdb` | 274 KB hoje; poucos MB depois da [F02](../fatias/F02-concluir-migracao-duckdb.md) | **sim** — é o produto |
| `data/raw/` | **2,5 GB** e crescendo ~450 MB/mês | não — é regenerável do FTP |

Se a [D02](D02-modelo-de-execucao.md) escolher execução efêmera, **o warehouse não
pode viver no disco do compute** — ele some ao fim do run.

## A restrição que manda aqui

O `CLAUDE.MD` documenta corretamente: DuckDB aceita **ou** vários leitores read-only
**ou** um único processo leitura-e-escrita. Qualquer consumidor persistente
(dashboard, notebook aberto) **bloqueia a escrita do pipeline**.

Hoje isso é inofensivo — não há consumidor. Mas a [F10](../fatias/F10-camada-analitica.md)
cria um, e aí a restrição morde.

## Opções para o warehouse

### A. Disco persistente da VM
| ✅ | Simples; é o que já funciona |
| ❌ | Amarra à VM 24/7; incompatível com efêmero |

### B. Object storage (S3 / R2 / GCS) ✅ recomendada
| ✅ | Sobrevive ao compute; versionamento e backup embutidos no serviço |
| ✅ | Custo desprezível para poucos MB (R2 tem free tier generoso) |
| ✅ | DuckDB lê direto via `httpfs` — a extensão **já está no `profiles.yml`** |
| ⚠️ | Escrita não é in-place: o padrão é baixar → rodar dbt → subir de volta |
| ⚠️ | Exige lock lógico para não ter dois runs simultâneos sobrescrevendo |

### C. Postgres gerenciado
| ✅ | Resolve concorrência de vez |
| ❌ | Contradiz [D01](D01-duckdb-only-ou-postgres.md) se a escolha for DuckDB-only |
| ❌ | Caro para 24 linhas |

### D. Commitar o `.duckdb` no git
| ✅ | Grátis, versionado, e o avaliador vê o resultado sem rodar nada |
| ❌ | Binário no git incha o repositório a cada run |
| ⚠️ | Viável só para um **export pequeno** (`.csv`/`.parquet` do mart), não o warehouse |

## Recomendação

**Warehouse: B** (object storage), com o padrão baixar → transformar → subir.

**Raw: efêmero.** Baixar, extrair, processar e **apagar no mesmo run**
([F07](../fatias/F07-retencao-e-permissoes.md)). São 450 MB para extrair ~1.500 linhas
úteis — guardar isso é pagar aluguel por lixo. O FTP é a fonte de verdade; se precisar
de novo, baixa de novo.

**Bônus que resolve a concorrência:** exporte o mart como **`.parquet` ou `.csv`** ao
fim de cada run, e faça os consumidores (notebook, gráfico do README, CrewAI) lerem
**o export**, não o `.duckdb`. Isso elimina a disputa de lock por desenho, e o export é
pequeno o bastante para ser commitado — atacando de quebra o problema de "não dá para
ver nada sem rodar" da [F10](../fatias/F10-camada-analitica.md).

## Decisão

> **Data:** 21/09/2026
> **Escolha:** **A** — `.duckdb` no disco da VM, **sem backup**.
> **Porquê:** os dados são públicos e o pipeline os regenera; se o arquivo se perder,
> roda-se tudo de novo. A premissa "execução efêmera" que levava à recomendação B
> (object storage) deixou de valer com a [D02](D02-modelo-de-execucao.md) = A.

### O que muda em relação ao que o doc recomendava

| | Antes | Depois |
|---|---|---|
| Warehouse | object storage (B), baixar → dbt → subir | disco da VM (A) |
| Backup | embutido no serviço de storage | nenhum; recuperação = reprocessar |
| [F13](../fatias/F13-migracao-nuvem.md) item 5 e critério de aceite | "backup com restauração testada"; "recuperando o warehouse" | "**reconstrução** testada a partir do FTP" *(editado)* |
| Estado de envio da [F15](../fatias/F15-entrega-por-email-e-arquivo.md) | tabela no warehouse | `envios.json` no repositório do arquivo *(editado)* |

### Riscos aceitos (a revisar)

1. ~~"É só rodar de novo" pressupõe que o FTP do PDET mantém o histórico.~~ **Verificado
   em 22/09/2026:** das 81 competências entre jan/2020 e set/2026, **79 têm
   `CAGEDMOV` publicado** no FTP; só 202608 e 202609 ainda não foram publicadas (defasagem
   normal do PDET). **Decisão do usuário:** o histórico completo desde jan/2020 **deve
   ser constituído** — não é opcional, é escopo. Isso amplia o alcance da F16 (que hoje
   parte de fev/2020 assumindo isso) para incluir um **backfill** das ~79 competências
   existentes, não só a operação corrente a partir de onde o projeto está hoje
   (202605 localmente).
2. **Reprocessar pode dar números diferentes** dos já enviados: o CAGED recebe
   declarações fora do prazo e exclusões que corrigem meses anteriores
   ([F12](../fatias/F12-for-exc-reconciliacao.md)). Por isso o arquivo dos boletins
   *enviados* não é regenerável e tem o próprio repositório (F15).
3. **O estado de envio não pode viver no warehouse.** Se vivesse, apagar o `.duckdb`
   faria o próximo run reenviar todas as competências à lista inteira. Por isso a F15
   guarda esse estado no repositório do arquivo.
4. O `.duckdb` reconstruído leva o tempo de reprocessar todas as competências
   (~55 MB baixados e ~450 MB extraídos por mês, em média).
5. **Nem tudo é regenerável:** o **marco zero** do estoque (31/12/2019,
   [D11](D11-estoque-de-emprego.md)) é inserido à mão. Ele precisa viver no git (como
   *seed* do dbt), fora do warehouse, ou a "reconstrução do zero" perde o estoque.
6. **O warehouse passa a guardar as movimentações de Sergipe** (não só o mart), porque o
   raw é apagado e o estoque é cumulativo ([F16](../fatias/F16-estoque-a-partir-do-marco-zero.md)).
   O tamanho ainda não foi medido na VM.
