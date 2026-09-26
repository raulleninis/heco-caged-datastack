# F12 · Ingestão de FOR/EXC e mart de reconciliação

| | |
|---|---|
| **Status** | 🟡 **Implantada em produção (26/09/2026); falta só a validação contra o painel do PDET** — ver "Registro de implementação" |
| **Esforço** | L (1 a 3 dias) |
| **Fase** | produção |
| **Depende de** | [F09](F09-testes-de-qualidade.md) |
| **Resolve** | Achado H |

## Contexto

Este é o único item desta revisão que o `README.md` **já documenta corretamente** —
inclusive com a nota explicando a consolidação em três arquivos. A fatia existe para
dimensionar o trabalho, não para revelar um problema.

Confirmado no FTP:

```
/pdet/microdados/NOVO CAGED/2026/202607/
  ['CAGEDEXC202607.7z', 'CAGEDFOR202607.7z', 'CAGEDMOV202607.7z']
```

O pipeline ingere **só o `CAGEDMOV`**. Portanto todo número publicado hoje é
**provisório e subestimado** para competências recentes.

| arquivo | conteúdo | efeito no saldo |
|---|---|---|
| `CAGEDMOV` | declarado dentro do prazo | base (é só isso que existe hoje) |
| `CAGEDFOR` | declarado fora do prazo | **soma** o saldo registrado |
| `CAGEDEXC` | exclusão de eventos já declarados | **subtrai** o saldo registrado |

**Sinal da exclusão (verificado em 22/09/2026 com `CAGEDEXC202607`):** a coluna
`saldomovimentacao` do EXC **preserva o sinal do evento excluído**, não o inverte. Uma
admissão excluída aparece com `+1` e tem efeito `−1`; um desligamento excluído aparece
com `−1` e tem efeito `+1`. Por isso se **subtrai** o saldo registrado.

**Também verificado (dois meses: 202606 e 202607):**

| | |
|---|---|
| FOR e EXC são **incrementais** | 0 linhas idênticas entre os dois meses; no FOR, `competenciadec` = mês do arquivo |
| Alcance de `competenciamov` | FOR retroage ~12 meses; EXC retroage até 202001 |
| Colunas | FOR tem as 28 do MOV; EXC tem 30 (`competenciaexc`, `indicadordeexclusao`) |

O estoque que usa estes arquivos é a [F16](F16-estoque-a-partir-do-marco-zero.md).

## Por que isso vale mais que parece

Numa entrevista para vaga de dados, "eu sei que meu número é provisório, e este é o
modelo que o reconcilia" é uma resposta de **nível sênior**. A maioria dos projetos de
portfólio ignora revisão de dado — tratam a fonte como imutável.

É também a fatia que transforma o projeto de "ETL de arquivo" em **modelagem de
dado que muda no tempo**: chave composta, reprocessamento, versionamento de fato.

## Escopo

1. Generalizar o download: hoje `baixar_arquivo` monta `f"CAGEDMOV{competencia}.7z"`
   com o prefixo **fixo no código**
   ([ingest_caged.py:71](../../pipeline/flows/ingest_caged.py#L71)). Parametrizar por tipo.
2. Separar os `.txt` por tipo no disco — hoje tudo cai em `data/raw/extraido/` e a
   staging lê `*.txt` por **glob**. Se um `CAGEDFOR` cair ali, ele é
   **silenciosamente somado como se fosse MOV**. Esse é o risco mais agudo desta fatia:
   ela quebra a staging atual se feita sem cuidado.
3. Três modelos de staging (`stg_caged_movimentacoes`, `stg_caged_fora_do_prazo`,
   `stg_caged_exclusoes`).
4. Mart de reconciliação por **competência de movimentação**, combinando
   `MOV + FOR − EXC`.
5. Reprocessar competências antigas — uma competência é revisada por vários meses.
   Isso depende da varredura da [F06](F06-janela-resiliente.md).
6. Expor no mart a distinção entre número **provisório** e **consolidado**, com a
   data de corte. Um número sem essa marcação será mal interpretado.

## Ponto de modelagem

A partir daqui, `competencia_mov` deixa de ser chave e vira
`(competencia_mov, competencia_dec)` — a staging **já carrega `competencia_dec` e
`indicador_de_fora_do_prazo`** e não usa nenhum dos dois. O dado necessário já está
ingerido.

## Critério de aceite

```sql
-- para uma competência antiga (ex.: 202601), o saldo reconciliado
-- deve diferir do saldo só-MOV, e a diferença deve ser explicável
select competencia_mov, saldo_mov, saldo_fora_prazo, saldo_exclusoes, saldo_consolidado
from mart_caged_reconciliado order by 1;
```

E a validação externa que fecha a conta: comparar o saldo consolidado com o número
publicado no **painel oficial do PDET** para o mesmo município e competência.
Se bater, o modelo está certo — e isso é uma frase muito boa de se dizer numa entrevista.

---

## Registro de implementação (26/09/2026)

Feita em duas partes, **validada em um warehouse de teste** (cópia do de produção, com o FTP real) e
**implantada em produção em 26/09/2026** (ver "Implantação").

### Parte 1 — ingestão
| escopo | o que foi feito |
|---|---|
| 1. Generalizar o download | `baixar_arquivo(competencia, tipo)`; `arquivos_no_ftp` devolve quais tipos existem; o flow decide por **arquivo (tipo, competência)** |
| 2. Separar os `.txt` por tipo | **Não foi preciso separar pastas.** O risco descrito (glob somar FOR/EXC como MOV) já não existia: a fonte lê `CAGEDMOV*.txt` com prefixo. Cada fonte nova tem o seu (`CAGEDFOR*`, `CAGEDEXC*`), então não se misturam |
| 3. Três modelos de staging | `stg_caged_movimentacoes` (refatorada, ver abaixo), `stg_caged_fora_do_prazo`, `stg_caged_exclusoes`, com macros compartilhadas (`dbt/macros/caged.sql`) |
| 5. Reprocessar antigas | Não há reprocessamento: FOR/EXC são **incrementais entre si** (cada arquivo é carregado uma vez) e as competências antigas são revisadas por **arquivos novos**. O mart recalcula tudo a cada run |

- **Chave da staging de FOR/EXC:** `competencia_arquivo` (o AAAAMM do nome, via `filename=true`),
  não `competencia_mov`: um arquivo traz movimentações de vários meses. Carga por arquivo,
  `delete+insert`, idempotente.
- **Registro de ingestão (`ingestao_arquivos`):** criado pelo flow. Necessário porque **11 arquivos EXC
  têm zero linhas de Socorro**; sem ele seriam rebaixados todo dia.
- **Regressão do refator do MOV:** reprocessei 202607 com o SQL novo e comparei com a produção: mesmas
  1.847 linhas e o mesmo hash de todas as colunas.
- **Backfill:** `backfill 2020..2026 --tipos FOR,EXC` (novo: intervalo de anos e filtro de tipo; pula o
  que já está carregado, `--refazer` reprocessa). Levou ~28 min no teste; cada ano passou nos 51 testes do dbt.

### Parte 2 — reconciliação
| escopo | o que foi feito |
|---|---|
| 4. Mart de reconciliação | `mart_caged_reconciliado` (competência de movimentação × grupamento): `saldo_mov`, `saldo_fora_prazo`, `saldo_exclusoes` (já com o efeito), `saldo_consolidado` |
| 6. Provisório x consolidado | colunas `situacao`, `defasagem_meses` e `ultima_competencia_carregada` |

**Testes novos:** `test_exc_preserva_sinal_do_evento` (trava a premissa do D11), `test_coerencia_reconciliado`
(consolidado = MOV + FOR + EXC, e o `saldo_mov` bate com o mart só-MOV), `test_continuidade_mov` (erro) e
`test_continuidade_for_exc` (warn). Mais 41 testes Python no total (`pipeline/tests`).

**O que os dados reais mostraram:**

| | |
|---|---|
| Arquivos carregados | FOR 78 (202002–202607), EXC 76 (202004–202607): exatamente o que o FTP tem |
| Linhas de Socorro | 2.746 (FOR) e 284 (EXC) |
| Defasagem do FOR | **máximo 12 meses** (p99 = 12; 100% dentro de 12) → o limite de "provisório" de 12 meses é uma medição |
| Defasagem do EXC | mediana 7, p90 26, **máximo 68 meses** (66% dentro de 12) → "consolidado" não é imutável |
| FOR/EXC com movimentação < 202001 | 0 → o ajuste do marco zero da F16 sai vazio, como previsto |
| Mart | 387 linhas, 79 competências: 67 consolidadas, 12 provisórias; nenhum saldo consolidado negativo |
| Efeito no total 2020–2026 | saldo só-MOV **3.463** → consolidado **3.381** (−82) |

Critério de aceite (a diferença existe e é explicável): 202601 (MOV −138, FOR +2, EXC 0 → −136);
202606 (MOV +55, FOR −10, EXC +1 → **+46**); 202512 (MOV −319, FOR −8, EXC +4 → −323).

### Decisões tomadas (revisáveis)
- **Salários continuam só no mart do MOV.** A mediana de quem entrou fora do prazo não se soma nem se
  subtrai da mediana do MOV. O boletim diz isso nas notas.
- **`meses_para_consolidar = 12`**, ajustável por `--vars`.
- **Filtro territorial mantido** (`município = 280480`); a F16 o generaliza.
- **O boletim (F15) passa a usar o mart reconciliado**, com barras claras para o provisório, a linha
  "saldo declarado no prazo → após fora do prazo e exclusões" e notas novas. Sem o mart, cai no só-MOV.
  Os boletins já enviados **não** mudam (o arquivo não se regenera): o de 202607 foi enviado só-MOV.
- Ao testar o boletim apareceu um **defeito da F15**: a comparação com o mesmo mês do ano anterior saía
  "indisponível" (buscava só na janela de 12 meses do gráfico). Corrigido, com teste.

### Implantação (26/09/2026)
O `./dbt` é montado ao vivo no container, então os modelos e testes novos ficaram visíveis para a produção
antes do código Python novo; isso era seguro só enquanto o PDET não publicasse a 202608 (sem competência nova
o flow antigo não chama o dbt). Por isso a implantação foi feita no mesmo dia:

1. `docker compose up -d --build` (flows novos), sem nenhum flow em execução e longe do cron (06:00 UTC).
2. `docker compose run -d --rm --name backfill-fe pipeline python flows/ingest_caged.py backfill 2020..2026 --tipos FOR,EXC`
   (~30 min; 7 flow runs, todos `Completed`; cada ano passou nos 51 testes do dbt).
3. Conferido no warehouse de produção: `ingestao_arquivos` com FOR 78 e EXC 76 (11 EXC com zero linhas),
   `mart_caged_reconciliado` com 387 linhas e 79 competências (67 consolidadas, 12 provisórias), saldo
   2020–2026 de 3.463 (só-MOV) para 3.381 (consolidado), e `data/raw/extraido` vazio. O `dbt test`
   completo tem só 3 avisos, todos de plausibilidade de salário (`test_faixa_salario_plausivel`,
   `test_media_vs_mediana_salario`, `test_salario_individual_plausivel`), que já existiam no histórico
   inteiro e disparam o alerta "testes em WARN" a cada `_transformar`; o de continuidade FOR/EXC zerou.

### Falta
- **Validação externa** (a que fecha o critério de aceite): comparar o `saldo_consolidado` de Socorro
  com o painel oficial do PDET para o mesmo município e competência (por exemplo 202601 = −136 e
  202606 = +46). Só o usuário consegue consultar.
- Decidir o que fazer com os 3 avisos de plausibilidade de salário do histórico (fora do escopo da F12).
