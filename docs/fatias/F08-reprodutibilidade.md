# F08 · Reprodutibilidade do ambiente

| | |
|---|---|
| **Esforço** | S (menos de 1 h) |
| **Fase** | pré-produção |
| **Depende de** | [F01](F01-destravar-o-clone.md) |
| **Resolve** | Achados J, K, L ([evidência E9](../revisao/03-evidencias.md#e9-deriva-de-versões-e-dependência-morta)) |

## Problema

`requirements.txt` usa faixas largas. O que a imagem tem **hoje**:

| pedido | instalado |
|---|---|
| `prefect>=3.0,<4.0` | 3.8.0 |
| `dbt-core>=1.8,<2.0` | **1.12.0** |
| `dbt-duckdb>=1.9,<2.0` | 1.10.1 |
| `duckdb>=1.1,<2.0` | **1.5.5** |
| `pandas>=2.0` | **3.0.5** |
| `py7zr>=0.21,<1.0` | 0.22.0 |

Três problemas distintos:

### 1. `pandas>=2.0` deixou entrar pandas 3.x

Sem teto de major. pandas 3 tem breaking changes em relação ao 2 — e o projeto
foi escrito quando 2.x era o corrente.

### 2. pandas nunca é usado

```bash
$ grep -rn "pandas" --include="*.py" .
(nenhuma ocorrência)
```

É dependência morta, carregando peso numa imagem de **1,19 GB**.

### 3. O YAML do dbt já exige 1.10+, mas o requirements aceita 1.8

```yaml
- accepted_values:
    arguments:          # <- sintaxe dbt >= 1.10
      values: [28]
```
— [_staging.yml:13-15](../../dbt/models/staging/_staging.yml#L13-L15)

Um `docker build` que resolva `dbt-core` para 1.8 ou 1.9 **quebra o parse dos testes**.
O piso declarado é incompatível com o código.

### Por que isso é sério para um projeto de vitrine

Um `docker build` feito hoje e outro feito em três meses produzem ambientes
**diferentes**. Se um avaliador clonar e der build, ele não roda o que você testou.
"Funciona na minha máquina" é exatamente o que containers deveriam eliminar — e aqui
não eliminam, porque as versões não estão presas.

## Escopo

1. **Remover pandas** do `requirements.txt`.
2. **Pinar versões exatas** (`==`) ou gerar um lockfile
   (`pip-compile` / `uv pip compile`), mantendo um arquivo de entrada legível.
3. **Subir o piso do dbt** para `>=1.10`, coerente com a sintaxe já usada.
4. Adicionar `require-dbt-version` no `dbt_project.yml`, para que o dbt reclame
   explicitamente em vez de falhar no parse.
5. Pinar a imagem base (`python:3.11-slim` → tag com digest) e trocar
   `prefecthq/prefect:3-latest` por uma versão fixa — `:3-latest` muda sob seus pés.
6. Reduzir a imagem: 1,19 GB para um flow que baixa FTP e chama dbt é muito.
   Remover pandas já ajuda; `--no-compile` e limpeza de cache ajudam mais.

## Critério de aceite

```bash
docker build --no-cache -t teste ./pipeline
docker run --rm teste pip list | grep -iE "prefect|dbt|duckdb|py7zr"
# -> versões idênticas às pinadas, reproduzíveis entre builds

docker run --rm teste pip list | grep -i pandas
# -> vazio

docker images teste --format '{{.Size}}'
# -> menor que 1,19 GB
```
