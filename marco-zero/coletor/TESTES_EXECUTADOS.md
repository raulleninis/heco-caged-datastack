# Verificação do pacote

Execução real em 28/09/2026, Windows, Python 3.12 e Microsoft Edge em modo headless. As versões das bibliotecas usadas estão em `VERSOES_TESTADAS.json`. O pacote não depende do caminho em que foi testado.

## Testes automatizados

Seis testes passaram:

1. Decodificação DSR com dicionário, repetição, zero, negativo e null.
2. Respostas escalares com células nomeadas, usadas no catálogo de UF.
3. Rejeição de continuação/paginação não suportada.
4. Seleção de competências e rejeição de período indisponível.
5. Saldo negativo e estoque vazio preservados como medidas distintas.
6. Comparação DuckDB somente leitura, sem reaplicar ajustes e sem modificar os bytes do banco de teste.

Todos os módulos passaram pela compilação de sintaxe do Python.

## Integração real com o painel

- Descoberta do modelo/esquema a partir da URL pública, sem arquivos capturados anteriormente.
- Resolução dos nomes de Socorro e Sergipe pelo catálogo do painel.
- Coleta de janeiro/2020, março/2020 e julho/2026 para os dois territórios.
- Seis recortes, com consultas separadas de grupos e totais; 39 linhas exportadas.
- CSV e Excel reabertos e comparados com os valores coletados.
- Sergipe, julho/2026, Não Identificado: admissões 0, desligamentos 2, saldo -2, estoque null. O null permaneceu vazio no Excel/CSV.
- Comparação de Socorro com o DuckDB fornecido na investigação: 54 comparações de medidas; 31 diferenças local/oficial, restritas a janeiro e março de 2020. Julho de 2026 coincidiu. Estoque não foi comparado localmente porque o mart não possui a coluna.

## Integração real com o FTP

O script opcional baixou e extraiu CAGEDMOV202001.7z, filtrou Nossa Senhora do Socorro e conferiu as contagens por competência, CNAE, seção e sinal contra a staging. Nenhuma diferença foi encontrada. Os demais arquivos não foram rebaixados no teste deste pacote.

## Limites desta verificação

O teste do pacote foi uma amostra funcional, não uma nova auditoria de todos os meses ou de todos os municípios. Linux/macOS e outros esquemas DuckDB não foram executados neste ambiente. Cada usuário deve fazer a coleta pequena recomendada no README e validar o mapeamento de sua base antes de ampliar o recorte.

Os dados de teste, o banco local e os arquivos nacionais do FTP não fazem parte do ZIP distribuído.

## Integração ao pipeline (28/09/2026, Linux)

Três correções para usar o coletor no repositório:

- `recorte.json` grava `ultima_competencia_disponivel` e `atualizacao_modelo`, que viram o
  `retificacoes_ate` e a fonte do marco zero.
- O comparador aceita staging com a UF inteira (o município declarado precisa estar nela; a
  confirmação fica registrada) e coluna de território em texto (`TRY_CAST`).
- O exemplo compara o estoque com o `mart_estoque` e inclui `202003` no período.

Verificação: oito testes passaram (dois novos) em `python:3.11.10-slim-bookworm`. A comparação do
estoque do painel (valores de `marco-zero/validacao/` e `marco-zero/estoque/`) com o `mart_estoque`
real, numa cópia do warehouse: 420 comparações, nenhuma diferença. `normalizar.py --coleta` sobre
uma pasta simulada no formato do coletor (com BOM) reproduziu os arquivos de `estoque/` e
`validacao/` atuais. A coleta pelo navegador não foi repetida nesta etapa.
