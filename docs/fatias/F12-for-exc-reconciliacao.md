# F12 · Ingestão de FOR/EXC e mart de reconciliação

| | |
|---|---|
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
