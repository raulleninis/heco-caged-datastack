# F11 · Observabilidade e alerta de falha

| | |
|---|---|
| **Status** | ✅ Implementada (24/09/2026) — falta configurar `NTFY_URL`/`HEARTBEAT_URL` e o teste de uma semana (ver "Resultado") |
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

## Resultado (24/09/2026)

| Escopo | Como ficou |
|---|---|
| 1. Alerta de falha | hooks `on_failure`/`on_crashed` nos dois flows ([alertas.py](../../pipeline/flows/alertas.py)) enviam ao **ntfy** (`NTFY_URL`). Feito em código, não em Automations do Prefect: não depende de blocos com segredo no banco do Prefect |
| 2. Alerta de silêncio | `verificar_defasagem()` (limite 60 dias) roda em **todo** run, inclusive sem nada novo. Escolhi checar no flow, não em teste dbt: o teste só roda quando há ingestão, e o caso a pegar é justamente o run sem nada novo. Além disso, **heartbeat externo** (`HEARTBEAT_URL`, healthchecks.io ou similar): ping em run verde, `/fail` em falha, alerta pela ausência |
| 3. Três estados | não publicada → verde + registrado (artifact e log); ingerida → verde; defasada → run vermelho + alerta |
| 4. Métricas | artifact markdown `metricas-ingestao` por run (MB baixados, linhas do município, tempos) + alerta se uma competência tiver < 50% da mediana das demais |

Também: testes dbt de plausibilidade viraram `severity: warn` (D04) e o flow
alerta quando reprovam; a `freshness` do source foi removida (incompatível com o
`.txt` apagado).

**Validado** (dbt real, dados reais 202601-202605, servidor HTTP local no lugar do
ntfy/healthchecks): carga do flow pelo mesmo caminho do worker (`flows/ingest_caged.py`
a partir de `/app`); defasagem 30 e 60 dias passa, 62 falha; ntfy recebe o JSON
esperado; heartbeat `/ping` e `/ping/fail`; sem variável = no-op sem erro; canal fora do
ar não derruba o flow; run sem novidade e defasado → vermelho + 1 alerta + só `/fail`;
run sem novidade e em dia → verde + só ping de sucesso, zero alertas; teste dbt em
WARN → detectado, alerta enviado, dado carregado e `.txt` apagado.

**Não validado** (dependem de você):
- envio a um ntfy/healthchecks **reais**: configure `NTFY_URL` e `HEARTBEAT_URL` no `.env`;
- no healthchecks.io, período de 1 dia + tolerância (o cron é diário, 03:00);
- o "teste honesto" do critério de aceite (desligar o agendador por uma semana).
