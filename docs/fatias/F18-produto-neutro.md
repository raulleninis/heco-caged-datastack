# F18 · Produto neutro: de Socorro para um repositório replicável

| | |
|---|---|
| **Status** | proposta (28/09/2026) |
| **Esforço** | L (1 a 3 dias), em partes; a parte E só acontece quando o critério de estabilidade for atingido |
| **Fase** | vitrine |
| **Depende de** | [F16](F16-estoque-a-partir-do-marco-zero.md) (territórios configuráveis), coletor do marco zero ([marco-zero/coletor/](../../marco-zero/coletor/README.md)) |
| **Revisa** | [D07](../decisoes/D07-repositorio-publico.md): o repositório público passa a ser um **repositório novo**, não este |
| **Objetivo** | Transformar o pipeline num produto que qualquer município hospeda, com Socorro como uma instância privada dele |

## Problema

O repositório nasceu para Nossa Senhora do Socorro e mistura três coisas:

- **produto:** ingestão, dbt, estoque, boletim, entrega, observabilidade;
- **instância de Socorro:** territórios, marco zero, destinatários, `.env`, auditorias, histórico;
- **produto interno** da prefeitura: a análise (ex-[F10](F10-camada-analitica.md)) e o boletim
  com IA, que já vivem fora daqui.

Duas restrições impedem simplesmente abrir este repositório:

1. o vínculo do autor com a administração municipal de Socorro;
2. o histórico de commits, que é todo sobre Socorro.

## Decisões já tomadas (28/09/2026)

- **Estrutura:** fork com `upstream` (opção B). O produto é o repositório principal. A instância
  de Socorro é um clone privado dele que só acrescenta configuração e recebe atualizações com
  `git pull upstream <versão>`.
- **Regra:** código só se muda no produto. O que só faz sentido para Socorro é configuração da
  instância ou vai para o produto interno.
- **Ordem:** o desenvolvimento continua **neste repositório** até o produto estar completo e
  estável (partes A a D). O desacoplamento (parte E) vem depois.
- **Histórico:** o repositório público nasce com histórico novo. Este repositório fica privado e
  arquivado, com todo o histórico, as auditorias e as decisões.
- **Evolução:** publicar uma imagem Docker versionada (opção C) só quando houver uma segunda cidade
  de verdade.

## Decisões pendentes

| decisão | bloqueia | observação |
|---|---|---|
| **nome do produto** | parte E | vira o nome do repositório público |
| **cidade de exemplo** | parte C | se o objetivo é se desvincular de Socorro, uma cidade de outro estado corta a associação e prova o guia de replicação |
| **licença** | parte E | um repositório público sem licença não pode ser reutilizado legalmente; MIT ou Apache-2.0 são as usuais |
| **fonte única da configuração do território** | parte A | hoje o município está em três lugares: `dbt_project.yml` (`municipio_boletim`), `boletim.py` (`TERRITORIO`) e os textos; ver A.2 |
| **quais documentos vão para o público** | parte D | as decisões D01 a D11 mostram o raciocínio, mas estão cheias de números de Socorro |

## Inventário (28/09/2026)

O que está preso a Socorro ou a Sergipe. Não entram na contagem: `docs/`, os CSVs e o coletor.

| onde | o quê | vira |
|---|---|---|
| `stg_caged_movimentacoes.sql`, `stg_caged_fora_do_prazo.sql`, `stg_caged_exclusoes.sql` | `where uf = 28` | variável `uf` |
| `dbt_project.yml` | `municipio_boletim: 280480` | configuração da instância |
| `pipeline/flows/boletim.py` | `TITULO`, `TERRITORIO = "280480"`, rodapés de fonte | nome e UF lidos da configuração ou do `territorios.csv` |
| `pipeline/flows/entrega.py` | corpo e assunto do e-mail | idem |
| `pipeline/flows/arquivo.py` | título da página do arquivo | idem |
| `dbt/tests/test_faixa_salario_plausivel.sql`, `test_salario_individual_plausivel.sql` | limites calibrados para Socorro | variáveis, com padrão documentado |
| comentários em SQL e Python (`ajuste_marco_zero`, `mart_estoque`, `estoque.sql`, stagings, `ingest_caged.py`) | exemplos com números de Socorro ou Sergipe | texto genérico, ou exemplos da cidade de exemplo |
| `dbt/models/marts/_marts.yml`, `_staging.yml` | fixtures de teste unitário com códigos de Sergipe | podem ficar (são dados de teste), ou migrar para a cidade de exemplo |
| `dbt/seeds/territorios.csv` | os cinco territórios de Sergipe | **instância** |
| `marco-zero/` (estoque, validação, originais, `FONTE.md`, `TERRITORIOS` do `normalizar.py`) | dados de Socorro e Sergipe | **instância**; o produto leva só o `normalizar.py --coleta` e o coletor |
| `marco-zero/coletor/` (README, prompt, configs, `TESTES_EXECUTADOS.md`) | exemplos com Socorro | cidade de exemplo |
| `docs/auditorias/`, `docs/revisao/` | auditoria de Socorro, revisão de 21/09 | **instância** (ficam no arquivo) |
| `README.md`, `CLAUDE.MD` | tudo escrito para Socorro | versão de produto (parte D) |
| `.env`, `secrets/`, `data/`, lista de destinatários | segredos, dados, LGPD | **instância**, nunca versionados |

## Escopo

### A. Parametrizar, sem mudar o comportamento de Socorro (neste repositório)

1. **UF da staging como variável** do dbt (`uf`), padrão sem valor: um produto sem UF configurada
   deve falhar com mensagem clara, não assumir Sergipe.
2. **Uma fonte só para o território do boletim.** Recomendação: `.env` (`CAGED_UF`,
   `CAGED_MUNICIPIO`), repassado ao dbt por `env_var()` e lido pelo Python. O nome vem do
   `territorios.csv`, o mesmo seed do estoque. Assim o `.env` da instância é o único lugar a
   mudar.
3. Títulos, assuntos e rodapés montados a partir dessa configuração.
4. Limites dos testes de salário como variáveis, com o valor de Socorro como padrão documentado
   da instância.
5. Comentários genéricos no código.

**Aceite:** um `grep -ri socorro` em `pipeline/`, `dbt/models`, `dbt/macros` e `dbt/tests` não
encontra nada. Com a configuração de Socorro, os marts ficam idênticos antes e depois
(`EXCEPT` nos dois sentidos, tabela a tabela), e o boletim sai com o mesmo conteúdo.

### B. Separar produto e instância dentro deste repositório

1. Classificar cada arquivo como produto, instância ou interno, a partir do inventário acima.
2. O produto passa a ter **exemplos** (`territorios.csv` da cidade de exemplo, `.env.example`
   completo). A instância substitui esses exemplos.
3. Documentar quais arquivos a instância pode alterar sem gerar conflito no `git pull upstream`.
   Se um arquivo de configuração conflitar, a instância prevalece; se o produto mudar o formato
   dele, a nota da versão diz o que migrar.

**Aceite:** a lista de arquivos de instância existe e é curta. Trocar de cidade = trocar só esses
arquivos.

### C. Cidade de exemplo de ponta a ponta

1. Rodar o coletor para a cidade escolhida (incluindo 202003 e meses posteriores).
2. `normalizar.py --coleta`, ativar a cidade no `territorios.csv` e reprocessar a UF dela.
3. Gerar o boletim da cidade de exemplo (arquivar, sem enviar e-mail).
4. Trocar os exemplos do coletor pela cidade de exemplo.

Cuidado: a staging guarda **uma UF**. Uma cidade de outro estado exige outro warehouse,
porque o raw é apagado depois da carga ([D06](../decisoes/D06-retencao-de-dados-brutos.md)).
Rode num diretório de dados separado, sem tocar no warehouse de Socorro.

**Aceite:** `test_estoque_confere_painel` passa para a cidade de exemplo, e o boletim dela é gerado
seguindo **só** o guia de replicação.

### D. Documentação de produto

1. README orientado a quem vai hospedar: o que é, um resultado (boletim da cidade de exemplo),
   como subir para a sua cidade, e depois a arquitetura.
2. Guia "adicione sua cidade": `.env`, coletor, `normalizar.py --coleta`, `territorios.csv`,
   primeira carga.
3. Versão genérica do `CLAUDE.MD` ([D09](../decisoes/D09-claude-md-na-vitrine.md)).
4. Decisões D01 a D11 reescritas sem números de Socorro, se a decisão pendente for levá-las.

### E. Desacoplar (só quando o critério de estabilidade for atingido)

**Critério de estabilidade:**

- partes A a D concluídas;
- dois fechamentos mensais seguidos de Socorro depois da parte A, sem regressão (mesmos números do
  painel e boletim entregue);
- um clone limpo sobe a cidade de exemplo seguindo só o guia.

**Passos:**

1. Criar o repositório público do produto com histórico novo, a partir de uma cópia sem os arquivos
   de instância. Marcar a versão `v1.0.0`.
2. Criar a instância de Socorro como repositório privado: clone do público, `upstream` apontando
   para ele, e um commit com os arquivos de instância.
3. **Migrar o servidor** para a instância, com checklist, porque o pipeline em produção roda a
   partir deste diretório:
   - pausar o agendamento;
   - clonar a instância ao lado deste diretório;
   - copiar `.env`, `secrets/` e `data/`, ou apontar os volumes para os mesmos caminhos;
   - subir a stack;
   - rodar um flow manual e conferir o warehouse, os testes, o heartbeat e o alerta;
   - só então retomar o agendamento.

   O estado dos envios da F15 vive no repositório do arquivo e não é afetado.
4. Arquivar este repositório (privado, somente leitura).
5. A [F14](F14-narrativa-do-repositorio.md) passa a acontecer no repositório público.

**Aceite:** o servidor roda a partir da instância, e o próximo fechamento mensal de Socorro sai
normalmente. Um `git pull upstream v1.0.x` na instância não gera conflito fora dos arquivos de
configuração. O repositório público não contém nenhuma menção a Socorro:
`git log -p | grep -i socorro` vazio.

## Fora de escopo

- A análise setorial e o boletim com IA: são produto interno ([D10](../decisoes/D10-escopo-analitico.md)).
- Suporte a várias UFs na mesma instalação: uma instalação atende uma UF. Várias UFs é trabalho
  para quando houver demanda.
- Imagem Docker publicada (opção C): só com uma segunda cidade real.
- A migração para a nuvem ([F13](F13-migracao-nuvem.md)): independe desta fatia, mas se as duas
  andarem juntas, a nuvem já deve subir a partir da instância.
