# Novo Caged — marco zero reproduzível

Mini projeto para uma pessoa abrir no **Claude Code ou Codex**, informar cidades/períodos e receber uma pasta com resultados oficiais, evidências, validações e comparação opcional com seu DuckDB.

Aqui, **marco zero** significa uma primeira coleta datada e reproduzível para servir de referência. Não significa reconstruir o estoque a partir de saldo, nem recuperar a versão dos dados publicada originalmente em 2020. Os meses históricos são consultados na **versão atual do painel**.

## O que está incluído

- Descoberta do modelo e esquema do painel público, usando navegador automatizado.
- Resolução de municípios por nome/UF ou código do Caged.
- Coleta de admissões, desligamentos, **saldo** e **estoque**, por grande grupamento e total.
- Resultados em uma única tabela longa: CSV, Excel e JSON.
- Preservação de valores negativos, zeros e **vazios/null**, sem confundir esses casos.
- Consulta independente dos totais e validação aritmética dos movimentos.
- Comparação opcional com um mart DuckDB, aberto somente para leitura.
- Auditoria opcional dos MOV/FOR/EXC atuais do FTP contra as stagings locais.
- Prompt pronto para orientar Claude Code/Codex e relatório determinístico para a IA interpretar.

Não há chave de API de IA no projeto: ele usa o assistente que a pessoa já tem. O código funciona também pelo terminal, sem IA. Não publica sites, não envia mensagens e não altera o banco local.

## Começar pelo Claude Code/Codex

1. Extraia/abra esta pasta no assistente com acesso ao terminal.
2. Cole o conteúdo de [PROMPT_PARA_AGENTE.md](PROMPT_PARA_AGENTE.md).
3. Informe cidades e estados, competências desejadas e, se quiser comparar, o caminho do DuckDB.
4. O assistente configura e executa os scripts, verifica as saídas e entrega o caminho da pasta criada.

Exemplo de pedido:

> Use este projeto para Nossa Senhora do Socorro, Aracaju, São Cristóvão e Barra dos Coqueiros, todos em Sergipe, e também o total de Sergipe. Quero junho e dezembro desde 2020, mais julho de 2026. Compare Socorro com meu banco em `C:/dados/caged.duckdb`. O mart já contém MOV + FOR − EXC. Entregue resultados, comparação e relatório, preservando meu banco.

Se não informar o banco, o assistente pode perguntar se deseja comparação local. **A ausência de DuckDB não impede a coleta oficial.**

## Ferramentas necessárias

| Ferramenta | Finalidade |
|---|---|
| Python 3.11 ou superior e pip | Executar os scripts |
| requests | Consultar o endpoint público do painel |
| Playwright + Chromium, Edge ou Chrome | Descobrir modelo e esquema sem capturas prévias |
| openpyxl | Gerar e reabrir o Excel para conferência |
| duckdb | Comparar a base local em modo somente leitura |
| py7zr | Descompactar os microdados na auditoria opcional do FTP |
| Claude Code/Codex com arquivos e terminal | Configurar, executar e interpretar as evidências |

Acesso à rede: HTTPS para Power BI e instalação de dependências. A auditoria opcional de microdados precisa também de FTP para `ftp.mtps.gov.br` (conexão de controle e dados em modo passivo).

Não é necessário instalar o DuckDB CLI, DBeaver, dbt, Prefect, Power BI Desktop ou conectores pagos. Permissões de rede/execução dependem do ambiente do assistente; conceda-as quando ele explicar a ação necessária.

## Instalação pelo terminal

Execute os comandos **dentro desta pasta**. Crie um ambiente isolado.

Windows / PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
Copy-Item config.exemplo.json config.json
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe marco_zero.py executar --config config.json
```

Linux/macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
cp config.exemplo.json config.json
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python marco_zero.py executar --config config.json
```

Em Linux pode ser necessário instalar as dependências de sistema do navegador (`python -m playwright install --with-deps chromium`); isso pode pedir privilégios administrativos. Outra opção no Windows é definir `"navegador": "msedge"` e usar o Edge instalado. Para Chrome instalado, use `"chrome"`.

Nos exemplos abaixo, `python` representa o executável Python do ambiente virtual criado.

## Escolher cidades e estados

Edite `territorios` no `config.json`:

```json
"territorios": [
  {"tipo": "municipio", "uf": 28, "nome": "Nossa Senhora do Socorro"},
  {"tipo": "municipio", "uf": 28, "codigo": 280030},
  {"tipo": "uf", "codigo": 28, "nome": "Sergipe"}
]
```

- O nome municipal é resolvido no catálogo do próprio painel, com a UF obrigatória para evitar homônimos.
- O código municipal usado aqui é o **código de seis dígitos do painel/Caged**, não o código IBGE de sete dígitos.
- Se informar nome e código, o programa exige que coincidam.
- Para outros estados, troque `uf`/`codigo`. O programa valida os códigos no painel.
- O recorte estadual é consultado diretamente; não é a soma apenas das cidades escolhidas.

Para descobrir os códigos:

```bash
python marco_zero.py catalogo --config config.json --uf 28
```

O caminho de `municipios.json` aparecerá no terminal.

## Escolher competências

O exemplo principal coleta junho e dezembro desde 2020 até a última competência disponível, mais **março de 2020**, a competência do marco zero. Sem ela, a coleta não gera marco zero (`normalizar.py --coleta` recusa).

```json
"periodo": {
  "inicio": 202001,
  "fim": "ultima_disponivel",
  "meses_do_ano": [6, 12],
  "adicionais": [202003]
}
```

Para **todos os meses**, remova `meses_do_ano` e `adicionais`:

```json
"periodo": {"inicio": 202001, "fim": "ultima_disponivel"}
```

Para uma lista exata:

```json
"periodo": {"competencias": [202001, 202003, 202512, 202607]}
```

Ou copie [config.auditoria-2020-2025.exemplo.json](config.auditoria-2020-2025.exemplo.json), que compara todos os meses de 2020–2025 de Socorro quando um banco é informado.

Competências explícitas indisponíveis geram erro, em vez de uma planilha vazia. `ultima_disponivel` considera competências com admissões no modelo, e não simplesmente datas futuras do calendário. O recorte e a atualização do modelo ficam registrados na saída.

## Comparar com seu DuckDB

```bash
python marco_zero.py executar --config config.json --duckdb "C:/dados/caged.duckdb"
```

Ou defina `comparacao.duckdb` no JSON. Use barras `/` em caminhos do Windows, ou escape as barras invertidas como `\\`.

O exemplo compara o **estoque** com o `mart_estoque` do pipeline, que tem uma linha por território (coluna `territorio`, texto, com a UF como `28`):

```json
"comparacao": {
  "duckdb": null,
  "tabela": "main.mart_estoque",
  "municipio_da_base": null,
  "colunas": {
    "competencia": "competencia_mov",
    "grupamento": "grupamento",
    "admissoes": null,
    "desligamentos": null,
    "saldo": "saldo_consolidado",
    "estoque": "estoque",
    "municipio": "territorio"
  }
}
```

Para comparar admissões e desligamentos, use o `mart_caged_reconciliado` (um município só, o da variável `municipio_boletim` do dbt), como em [config.auditoria-2020-2025.exemplo.json](config.auditoria-2020-2025.exemplo.json).

- **O mart já deve conter a reconciliação.** O comparador não soma FOR nem subtrai EXC novamente.
- Sem coluna municipal, é obrigatório declarar `municipio_da_base`. Essa declaração impede comparar um mart de um município com todas as cidades. Quando a staging conhecida está disponível, o município declarado precisa estar nela. Se a staging tem **um** município, a declaração fica confirmada; se tem vários (a staging do pipeline guarda a UF inteira), ela só prova que o município existe, e `validacao_duckdb.json` registra `municipio_da_base_confirmado_pela_staging: false`.
- Se a tabela tem várias cidades, configure `colunas.municipio`. Os códigos devem ter a mesma convenção de seis dígitos do painel; coluna de texto é convertida (`TRY_CAST`), e linhas que não são município (como a UF `28` no `mart_estoque`) ficam de fora.
- O comparador agrega por competência e grupamento. A tabela configurada não pode conter linhas `TOTAL` junto com detalhes.
- `colunas.estoque: null` significa **medida não disponível para comparação local**. Ela continuará sendo coletada do painel.
- Esta implementação compara **municípios**. O total de UF é exportado e validado no painel, mas não é comparado ao banco municipal. Uma base estadual requer extensão explícita do comparador.
- Rótulos diferentes podem ser alinhados com `comparacao.mapa_grupamentos`, por exemplo `{"Agro": "Agropecuária"}`. Não use isso para disfarçar uma reclassificação real.
- Feche/desconecte DBeaver ou outros processos que bloqueiem o arquivo. O script não encerra aplicativos nem força acesso.

Também é possível comparar depois, sem nova coleta:

```bash
python marco_zero.py comparar --config config.json --duckdb "C:/dados/caged.duckdb" --pasta "saida/marco-zero-IDENTIFICADOR"
```

Esse comando escreve `comparacao_duckdb.csv` e `validacao_duckdb.json` na pasta indicada. O relatório criado anteriormente não é reescrito; consulte esses arquivos atualizados.

## O que a pessoa recebe

Cada execução cria uma pasta nova:

```text
saida/marco-zero-DATA_IDENTIFICADOR/
  status.json
  recorte.json                # territórios, competências, última competência disponível e atualização do modelo
  dados.csv
  dados.xlsx
  dados.json
  validacao.json
  RELATORIO.md
  comparacao_duckdb.csv       # se o banco foi informado
  validacao_duckdb.json       # se o banco foi informado
  schema_duckdb.json          # se o banco foi informado
  descoberta/
    sessao.json
    modelo.json
    schema.json
    pagina.txt
  evidencias/
    ... requisições e respostas públicas ...
```

Formato longo:

```text
competencia;tipo_territorio;codigo_territorio;regiao;grupamento;admissoes;desligamentos;saldo;estoque
```

CSV usa `;`, UTF-8 com BOM e campos vazios para null. JSON mantém `null`; Excel mantém células vazias. Há uma linha `TOTAL` por território/mês. **Não some TOTAL com seus componentes, nem UF com seus municípios.**

`status.json` deve terminar como `concluido`. Se estiver `falhou`, a pasta pode conter evidências e arquivos parciais; ela não deve ser apresentada como uma coleta concluída. Divergências no DuckDB não são erros de execução: são resultados da auditoria, discriminados no relatório.

## Validações e interpretação

- Admissões menos desligamentos deve coincidir com o saldo publicado; null dos movimentos é tratado como zero **somente na checagem**, sem alterar o arquivo exportado.
- Totais de admissões, desligamentos e saldo são consultados separadamente e comparados com os grupamentos.
- Estoque é consultado diretamente. Nunca é calculado como admissões menos desligamentos.
- Estoques vazios ou somas diferentes do total são registrados para análise. Não se preenche estoque pelo residual para forçar fechamento.
- O programa falha se o esquema mudar, a consulta atingir o limite suportado, faltar competência ou a atualização do modelo mudar durante a coleta.
- O decodificador suporta as respostas tabulares usadas aqui. Não é um leitor universal de todos os formatos Power BI.
- A comparação local distingue `IGUAL`, `DIVERGENTE`, `NULO_VS_VALOR`, `AUSENTE_LOCAL` e `AUSENTE_PAINEL`; delta é **local menos oficial**.
- A IA deve explicar as evidências e limitações. Ela não deve calcular números por aproximação nem declarar uma causa sem evidência.

## Investigar a causa com os microdados do FTP

Quando a diferença persistir, este comando opcional repete a verificação que fizemos dos arquivos da fonte:

```bash
python auditar_ftp.py --duckdb "C:/dados/caged.duckdb" --uf 28 --municipio 280480 --competencias-mov 202001 202003 --todos-ajustes --saida saida
```

Ele baixa os MOV indicados e os FOR/EXC registrados em `ingestao_arquivos`, guarda listagens e SHA-256, extrai os arquivos e compara contagens por competência da movimentação, subclasse CNAE, seção e sinal.

Esse utilitário pressupõe as tabelas `stg_caged_movimentacoes`, `stg_caged_fora_do_prazo`, `stg_caged_exclusoes` e os campos usados no projeto original. Se o esquema for diferente, a IA deve inspecioná-lo e adaptar explicitamente o utilitário antes de executar.

É uma auditoria **agregada**, não uma identificação de trabalhadores ou empregadores. `--todos-ajustes` cobre o manifesto local; não prova que não exista outro arquivo no FTP ainda não registrado. Os downloads são nacionais, mesmo quando a comparação é municipal, e podem ocupar bastante espaço. A pasta preserva os arquivos baixados; não há exclusão automática.

## Limites de manutenção

O coletor reproduz o endpoint público usado pelo navegador. Não é uma API contratual do MTE. Uma mudança do painel pode exigir atualização de nomes de campos, consultas ou decodificador. A descoberta evita IDs de modelo fixos, mas os nomes semânticos esperados são verificados e podem mudar.

Uma pasta de resultados é uma fotografia da versão consultada. Executar novamente pode produzir revisões históricas diferentes. Cada execução tem pasta própria; ela não reutiliza silenciosamente o cache antigo para uma nova coleta.

Os arquivos do projeto não incluem seu banco, capturas particulares, dependências instaladas ou credenciais. Os scripts foram organizados a partir da auditoria feita com o usuário, com correções para null e saldo. A descoberta exige um navegador somente na execução de coleta/catálogo; a comparação de uma pasta já pronta não precisa de navegador ou rede.

## Estrutura do código

| Arquivo | Responsabilidade |
|---|---|
| marco_zero.py | CLI, recortes, geração da pasta, CSV/Excel/JSON e relatório |
| painel.py | Descoberta, consultas públicas, decodificação e evidências |
| validacao.py | Conferência de saldo e totais |
| warehouse.py | Comparação opcional somente leitura com DuckDB |
| auditar_ftp.py | Investigação opcional dos microdados |
| tests/test_core.py | Testes dos casos críticos de dados e comparação |
| PROMPT_PARA_AGENTE.md | Instrução pronta para Claude Code/Codex |

Os testes locais não substituem a conferência real da fonte. Para um novo ambiente, comece com um território e duas competências; valide a amostra antes de executar uma série maior.

## Do resultado ao marco zero do pipeline

Uma coleta concluída que inclua `202003` vira o marco zero do pipeline com:

```bash
python3 marco-zero/normalizar.py --coleta marco-zero/coletor/saida/marco-zero-IDENTIFICADOR
```

O normalizador lê `dados.csv` e `recorte.json` e grava `marco-zero/estoque/<codigo>_<nome>.csv` (competência 202003) e `marco-zero/validacao/<codigo>_estoque_painel.csv` (competências posteriores). O código do território, o `retificacoes_ate` (= `ultima_competencia_disponivel`) e a data da coleta vêm da própria pasta. Depois, ative o território em `dbt/seeds/territorios.csv`. Ver [../LEIA-ME.md](../LEIA-ME.md).

