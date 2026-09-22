# F07 · Retenção do raw e containers não-root

| | |
|---|---|
| **Esforço** | S (menos de 1 h) |
| **Fase** | pré-produção |
| **Depende de** | [F04](F04-religar-dbt-no-flow.md) |
| **Resolve** | Achados G e I ([evidência E8](../revisao/03-evidencias.md#e8-raw-de-25-gb-sem-retenção-arquivos-pertencentes-a-root)) |

## Problema

### Crescimento sem limite

```
2,5G    data/raw
```

5 competências × ~450 MB de `.txt` extraído, mais os `.7z` originais. **Nada é apagado
nunca.** O `extrair_7z` extrai e segue; o `.7z` fica, o `.txt` fica.

Na VM caseira isso é um incômodo. Numa VM de nuvem, é **custo de disco recorrente** —
e a [F13](F13-migracao-nuvem.md) fica mais cara por um motivo evitável.

Vale notar a desproporção: são 450 MB de Brasil inteiro por mês, dos quais o projeto
usa **um município** — cerca de 1.500 linhas. A staging varre 2,5 GB para filtrar
`uf = 28 and município = 280480`.

### Arquivos pertencentes a root

```bash
$ docker run --rm datastack-pipeline:latest id
uid=0(root) gid=0(root)

$ ls -la data/raw/extraido/
-rw-r--r-- 1 root root 448833720 CAGEDMOV202601.txt
```

Os containers rodam como root e escrevem no bind mount `./data`. Os arquivos ficam
`root:root` **no host** — o usuário não consegue apagá-los sem `sudo`, e qualquer
script de limpeza rodando como usuário comum falha silenciosamente.

## Escopo

1. **Retenção**: definir política em [D06](../decisoes/D06-retencao-de-dados-brutos.md)
   e implementá-la como task do flow. Opções:
   - apagar o `.7z` após extração bem-sucedida (ganho imediato, baixo risco);
   - apagar o `.txt` após o `dbt run` (exige que a staging deixe de ser view — ver abaixo);
   - manter só as *N* competências mais recentes.
2. **Usuário não-root**: criar usuário no `Dockerfile` (`RUN useradd ...` + `USER`),
   com UID/GID alinhados ao dono de `./data` no host.
3. **Corrigir a posse atual**: `sudo chown -R $USER:$USER data/` uma vez.

## ⚠️ A dependência escondida: a staging é uma *view*

```sql
{{ config(materialized='view') }}
...
from read_csv_auto('/data/raw/extraido/*.txt', ...)
```

Como `stg_caged_movimentacoes` é **view**, ela relê os `.txt` a **cada consulta**.
Apagar os `.txt` quebra a staging e, por consequência, qualquer `dbt test` nela.

**Portanto:** apagar o `.txt` exige antes materializar a staging como `table`
(ou `incremental`). Isso é escopo da [F09](F09-testes-de-qualidade.md), e é a razão
pela qual esta fatia depende dela na prática, mesmo não dependendo no papel.

Um caminho seguro em duas etapas:
1. agora: apagar só os `.7z` (nada depende deles depois da extração);
2. depois da F09: materializar staging como tabela e passar a apagar os `.txt`.

## Critério de aceite

```bash
# depois de um run completo
ls data/raw/*.7z          # -> vazio (ou só a competência corrente)
docker run --rm datastack-pipeline:latest id   # -> uid != 0
ls -la data/raw/extraido/ # -> arquivos com o dono do host, não root
du -sh data/raw           # -> estável entre competências, não crescente
```
