# F04 · Religar o dbt no flow

| | |
|---|---|
| **Esforço** | S (menos de 1 h) |
| **Fase** | agora |
| **Depende de** | [F03](F03-agendamento-real.md) |

## Problema

O pipeline hoje **ingere mas não transforma**:

```python
    arquivo = baixar_arquivo(competencia)
    extrair_7z(arquivo)
    # run_dbt(["run"])
    # run_dbt(["test"])
```
— [ingest_caged.py:122-125](../../pipeline/flows/ingest_caged.py#L122-L125)

A task `run_dbt` está implementada e correta, mas as duas chamadas estão comentadas.
O flow baixa 450 MB, extrai, e para. Todo `dbt run` que aconteceu neste projeto foi
digitado à mão.

Como consequência, **o `backfill_caged` tem o mesmo buraco** — ele nem sequer
menciona `run_dbt`, então um backfill de ano inteiro deixa o warehouse intocado.

## Escopo

1. Descomentar as duas chamadas em `ingest_caged`.
2. Adicionar `run_dbt(["run"])` e `run_dbt(["test"])` ao final de `backfill_caged` —
   **uma vez só, depois do laço**, não a cada competência. A staging lê
   `/data/raw/extraido/*.txt` por glob, então rodar o dbt dentro do laço reprocessa
   tudo N vezes sem ganho.
3. Decidir o comportamento quando `dbt test` falha
   ([D04](../decisoes/D04-politica-de-falha-de-teste.md)): hoje `run_dbt` levanta
   `RuntimeError` em qualquer `returncode != 0`, o que marca o flow como falho.
   Isso está **certo** para `run`. Para `test`, pergunte-se se um teste de qualidade
   falhando deve derrubar o flow ou só alertar.
4. Melhorar o log de erro: hoje `logger.error(result.stderr)` — o dbt escreve a maior
   parte do diagnóstico no **stdout**, não no stderr. Em caso de falha, logue os dois.

## Ponto de atenção: concorrência do DuckDB

Depois da [F02](F02-concluir-migracao-duckdb.md), o `dbt run` passa a **escrever** no
`.duckdb`. Se qualquer outro processo estiver com o arquivo aberto (um notebook, um
`duckdb` interativo esquecido, um dashboard), o `dbt run` falha com lock.

Com o dbt rodando dentro do flow agendado às 3h, esse conflito vira **intermitente e
difícil de diagnosticar** — a falha só aparece quando alguém deixou uma conexão aberta.
Vale registrar a estratégia em [D03](../decisoes/D03-onde-guardar-os-dados.md).

## Critério de aceite

Um flow run disparado do zero produz, sem intervenção manual:

- o `.txt` da competência em `data/raw/extraido/`;
- o mart atualizado com a nova competência;
- os testes dbt executados, com resultado visível no log do flow run.

```bash
# depois de um run completo, a competência nova aparece no mart
select distinct competencia_mov from mart_caged_mensal_grupamento order by 1 desc limit 3;
```
