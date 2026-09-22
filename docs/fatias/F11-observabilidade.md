# F11 · Observabilidade e alerta de falha

| | |
|---|---|
| **Esforço** | M (meio dia) |
| **Fase** | produção |
| **Depende de** | [F06](F06-janela-resiliente.md) |
| **Resolve** | a causa de o Achado B ter passado despercebido |

## Problema

A pergunta que define esta fatia: **como você descobriu que o pipeline não roda desde
28 de julho?**

A resposta é: não descobriu. Foi preciso consultar a API do Prefect nesta revisão.
O projeto ficou ~2 meses parado, acumulou 2 competências de atraso, e **nenhum sinal
foi emitido**.

E há um agravante de desenho. O flow atual encerra assim:

```python
    if not arquivo_existe_no_ftp(competencia):
        logger.info("Encerrando sem erro -- tentamos de novo na próxima execução agendada.")
        return
```
— [ingest_caged.py:118-120](../../pipeline/flows/ingest_caged.py#L118-L120)

Isso é **correto** (não publicado ainda ≠ falha), mas cria um ponto cego:
"não publicou ainda" e "estou quebrado há dois meses" produzem **exatamente o mesmo
sinal** — um flow run verde. Um pipeline que sempre passa é indistinguível de um
pipeline que não roda.

## Escopo

### 1. Alerta ativo de falha

Notificação por canal que você realmente lê (e-mail, Telegram, Discord, ntfy) quando
um flow run falha. As Automations do Prefect cobrem isso sem código.

### 2. Alerta de *silêncio* — o que faltava aqui

O mais importante, e o que teria pego este caso: alertar quando **não houve run
bem-sucedido nas últimas N horas**, ou quando a competência mais recente no mart está
atrasada além do esperado.

Um teste dbt sobre a defasagem resolve boa parte:

```sql
-- falha se a competência mais recente do mart estiver
-- mais de ~70 dias atrás da data de hoje
select max(competencia_mov) from {{ ref('mart_caged_mensal_grupamento') }}
having ...
```

Detecta "parou de rodar", "FTP mudou de layout" e "downloads falhando em silêncio"
com um artefato só.

### 3. Distinguir os três estados

O flow precisa emitir sinais diferentes para:

| estado | hoje | deveria |
|---|---|---|
| competência não publicada ainda | verde | verde, mas **registrado** |
| competência publicada e ingerida | verde | verde |
| competência publicada há >30d e não ingerida | **verde** | **alerta** |

### 4. Métricas mínimas por run

Linhas ingeridas, competências processadas, duração, tamanho baixado. Sem isso não dá
para perceber que uma competência veio com metade das linhas.

## Cuidado: o alerta precisa ser externo ao que ele vigia

Se o alerta depender do Prefect, e o Prefect cair, não há alerta. Para a
[F13](F13-migracao-nuvem.md), considere um *heartbeat* externo (um serviço de
dead-man's-switch gratuito): o pipeline dá um "ping" ao terminar; **quem alerta é a
ausência do ping**.

Esse é justamente o desenho que teria pego a falha atual, porque não depende de nada
dentro da máquina parada.

## Critério de aceite

Simule os três cenários e confirme que **só o terceiro** gera alerta:

1. FTP sem a competência nova → sem alerta;
2. run bem-sucedido → sem alerta;
3. pipeline parado por mais que o limite → **alerta recebido no canal**.

E o teste honesto: **desligue o agendador por uma semana** e veja se você fica sabendo.
