# F20 · Estoque ancorado no estoque de referência do MTE

| | |
|---|---|
| **Esforço** | M (meio dia) |
| **Fase** | produção |
| **Depende de** | [F16](F16-estoque-a-partir-do-marco-zero.md) (mart_estoque, territórios), [F12](F12-for-exc-reconciliacao.md) (FOR/EXC) |
| **Decisões associadas** | [D11](../decisoes/D11-estoque-de-emprego.md) (revista em 01/10/2026) |

## Problema

Com a competência 202608 (publicada em 29/09/2026), o estoque de Socorro passou a divergir do
painel do Novo CAGED: **25.360 no projeto contra 25.364 no painel**, com Indústria −5 e Serviços
+1. O mesmo deslocamento aparecia no marco zero manual (mar/2020) comparado com o painel de
hoje, e até em jan/2020. A conta do projeto estava certa; o que mudou foi o nível do painel.

## O que foi investigado (01/10/2026)

- **FTP inteiro (`ftp.mtps.gov.br`, 9.317 entradas em `/pdet` e `/portal`).** Entre a atualização
  do painel usada no marco (28/08/2026) e a de 29/09/2026, só mudaram os três arquivos de
  202608. Os 236 arquivos MOV/FOR/EXC batem em tamanho com o registro de ingestão. Candidatos
  anteriores a 2020 foram descartados pela data: `CAGED_AJUSTES` (CAGED antigo, até 2019, pasta
  2020 vazia), RAIS 2019 (republicada em 24/04/2026) e CAGED antigo 2015–2019 (03/06/2026). Nenhum
  arquivo chamado "estoque de referência" no FTP.
- **O arquivo fica no gov.br, fora do FTP:**
  [Estoque de Referência](https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/acoes-e-programas/programas-projetos-acoes-obras-e-atividades/estatisticas-trabalho/estoque-de-referencia)
  (2022, 2023, 2024 e 2026). O de 2026: página atualizada em 17/06/2026; dentro do zip,
  `EstoquePAE2026CNAExMun.txt` de 25/05/2026, 668.903 linhas
  `codmun;cnae20subclas;estoqueref` (município × subclasse CNAE, Brasil inteiro). O servidor
  não manda `Last-Modified` e responde 403 a `HEAD`.

## Descoberta

O painel **não acumula movimentações desde 2020**. Ele ancora no estoque de referência (o de 2026
é o estoque ao fim de **dez/2025**) e soma ou subtrai os saldos a partir dele. Por isso uma
troca da referência desloca a série inteira, até 2020.

Prova, Socorro: referência 25.627 (Indústria 6.878, Serviços 11.146) + saldo do projeto de
202601 a 202608 (−263) = **25.364**, o número oficial; Indústria 6.803 e Serviços 10.731, também
os oficiais. Conferido pelo usuário no painel, com o cálculo a partir da referência:

| território | 202003 | 202608 | projeto (marco zero) − referência |
|---|---:|---:|---|
| Nossa Senhora do Socorro (280480) | 22.005 | 25.364 | Indústria −5, Serviços +1 |
| São Cristóvão (280670) | 9.172 | 12.091 | Comércio −33 |
| Aracaju (280030) | 154.907 | 195.389 | Indústria −1, Construção +4, Comércio +2, Serviços +3 |
| Sergipe (28) | 275.152 | 355.526 | Agro +1, Indústria −6, Construção +5, Comércio −34, Serviços +1 |
| Barra dos Coqueiros (280060) | 2.790 | 5.273 | nenhuma |

A diferença é a mesma em 202003 e em 202608, grupamento a grupamento: só o nível mudou, os
saldos mensais são os mesmos.

## Decisão

- O estoque passa a ser **ancorado no estoque de referência do MTE**, como no painel:
  `estoque(t) = referência ± saldos entre t e a competência da referência`.
- O **marco zero manual (F16) fica desativado, não excluído**: modelos, testes, source e a pasta
  `marco-zero/` continuam no repositório. Se o fluxo novo não der problema, sai de vez numa
  fatia futura.
- **Todo run do flow diário confere o arquivo do MTE antes da ingestão.** Mudou: baixa de novo,
  recarrega e recalcula o estoque de toda a série (mesmo sem competência nova). Não mudou: segue
  só com a ingestão.
- **Referência de um ano novo (ex.: 2027) só gera aviso**, uma vez. Trocar o ano reancora a série
  inteira e é decisão manual, depois de conferir com o painel.
- O estoque começa em **jan/2020** (`var('estoque_inicio')`). Conferido pelo usuário: de mar/2020
  em diante bate com o painel; **em jan e fev/2020, o estoque de Socorro fica 2 vínculos abaixo do painel** (o oficial tem 2 a mais). Recuar até
  eles passa pelo saldo de 202003, cujo `CAGEDMOV` no FTP diverge do painel
  ([auditoria](../auditorias/2026-09-28-painel-vs-mart-socorro.md)). Diferença aceita, mantida
  assim (decisão do usuário, 01/10/2026).

## Implementação

| peça | o quê |
|---|---|
| `pipeline/flows/estoque_referencia.py` | `verificar()`: baixa o zip do ano `ANO_REFERENCIA` (2026), compara o SHA-256 do `.txt` com o do último carregado e, se mudou, substitui `estoque_referencia` (só Sergipe, ~6.600 linhas) numa transação e registra em `estoque_referencia_arquivos`. Lê a página da pasta e avisa uma vez por ano novo (`estoque_referencia_avisos`). Falha de rede ou de formato nunca derruba o flow: alerta e segue com o que já está carregado. Manual: `python flows/estoque_referencia.py verificar` |
| `ingest_caged.py` | `verificar_estoque_referencia()` no início dos dois flows; `_materializar_marts()` (seed, `stg_estoque_referencia` + marts, testes) também roda quando a referência é carregada ou muda sem competência nova |
| `stg_estoque_referencia` | subclasse com 7 dígitos (o arquivo omite o zero à esquerda) → divisão → seção (seed `cnae_divisoes`) → `caged_grupamento`; 9999999 = Não Identificado, não a divisão 99 |
| `mart_estoque` | `referência + acumulado(t) − acumulado(ref)`; os seis grupamentos para todo território com referência (grupamento ausente no arquivo vale 0); desde 202001; NULL sem referência ou com a referência à frente dos dados carregados. Coluna `competencia_referencia` no lugar de `competencia_marco_zero` |
| Marco zero desativado | `dbt/models/marco_zero_desativado/` e `dbt/tests/marco_zero_desativado/` com `enabled: false` (dbt_project.yml); source `marco_zero` com `enabled: false`. As tabelas antigas (`stg_marco_zero_estoque`, `ajuste_marco_zero`) ficam no warehouse, sem atualização |
| Testes dbt | `test_estoque_confere_referencia` (error: na competência da referência, o mart é exatamente o arquivo somado), `test_territorio_sem_estoque_referencia` (warn); unitários: exclusão recuando da referência, município × UF, grupamento sem referência, referência à frente dos dados, subclasse → grupamento |
| Testes Python | `tests/test_estoque_referencia.py`: leitura do zip, hash pelo `.txt`, carregado/igual/mudou/indisponível, aviso de ano novo uma vez |
| Boletim | notas e textos dizem "estimativa a partir do estoque de referência do MTE". Muda a descrição de um fato do boletim com IA: o hash muda e a próxima geração chama o LLM de novo |

## Critério de aceite

- [x] Estoque de 202608 igual ao do painel nos cinco territórios (Socorro 25.364).
- [x] Estoque de 202003 igual ao calculado a partir da referência, conferido pelo usuário.
- [x] Mar/2020 em diante bate com o painel; jan e fev/2020 de Socorro 2 abaixo do painel, aceito.
- [x] `dbt test` sem erro; os 4 WARN são os de sempre (Não Identificado de Sergipe e salários).
- [x] Flow diário de ponta a ponta numa cópia do warehouse, com a referência adulterada: detecta,
  recarrega, recalcula sem competência nova e termina verde.
- [x] 157 testes Python passando.
- [ ] Algumas semanas de runs diários sem surpresa; aí remover o marco zero de vez (modelos,
  testes, source, `marco-zero/`, montagem no compose, coletor).

## Pontos abertos

- **A data em que o painel adotou a referência 2026 não está clara.** A página é de 17/06/2026,
  mas o marco coletado em 28/09 ainda batia com a série antiga. Pelo visto, o painel só passou a
  usá-la na atualização de 29/09/2026.
- **Hash diário sem `Last-Modified`:** o arquivo (2,3 MB) é baixado em todo run. É barato, e é o
  único jeito confiável de saber se mudou.
- **O nome dos arquivos de anos futuros é suposição** (`estoque-de-referencia-AAAA.zip`, o padrão
  de 2022–2026). Se o MTE mudar o padrão, o aviso de ano novo não dispara.
