# F17 · Teste de silêncio: provar que o alerta chega

| | |
|---|---|
| **Status** | 🟡 Em andamento (24/09/2026): itens 1 e 2 concluídos e confirmados no celular; item 3 (container parado) iniciado, aguardando o alerta de ausência |
| **Esforço** | XS de trabalho ativo (~30 min) + tempo de espera (26 h a 1 semana) |
| **Fase** | produção |
| **Depende de** | [F11](F11-observabilidade.md) |
| **Resolve** | os itens de F11 que só se validam com serviços reais: envio ao ntfy/healthchecks e o "teste honesto" do critério de aceite |

## Problema

A [F11](F11-observabilidade.md) foi validada com um servidor HTTP local no lugar do ntfy
e do healthchecks. Isso prova que o **código** envia a requisição certa; não prova que
ela **chega** ao seu celular. Um alerta que nunca foi visto chegando é decoração — o
mesmo raciocínio do "teste do teste" da [F09](F09-testes-de-qualidade.md).

O critério de aceite original da F11 termina assim: *"desligue o agendador por uma
semana e veja se você fica sabendo."* Esta fatia executa isso.

## Pré-requisitos

- `NTFY_URL` e `HEARTBEAT_URL` preenchidos no `.env` (feito em 24/09/2026);
- no healthchecks: período **1 dia**, tolerância (*grace*) **1 hora** (feito);
- o ntfy instalado/inscrito no celular, com o tópico configurado;
- stack no ar: `docker compose up -d --build`.

## Escopo

### 1. Smoke test dos dois canais (5 min)

```bash
# alerta ativo: deve aparecer no celular em segundos
docker compose exec pipeline python -c "
import sys; sys.path.insert(0, '/app/flows')
from alertas import notificar, ping_heartbeat
print(notificar('CAGED: teste F17', 'Se você leu isto, o canal ntfy funciona.', 'high'))
print(ping_heartbeat(True))
"
# -> imprime True e True
```

No painel do healthchecks, o check deve mudar para **Up** com o ping recém-chegado.

### 2. Alerta de falha real (10 min)

Force um run que falhe de verdade e confirme que o alerta chega **e** que o heartbeat
recebeu `/fail` (o check fica **Down** imediatamente, sem esperar o prazo):

```bash
# com o warehouse vazio, verificar_defasagem() levanta DefasagemExcedida
# (só se o FTP não tiver nada novo; senão o run ingere e fica verde)
docker compose exec pipeline python -c "
import sys; sys.path.insert(0, '/app/flows')
from ingest_caged import ingest_caged
ingest_caged()
"
```

Se o warehouse local já estiver defasado (última competência > 60 dias), este run
falha sozinho, sem nenhuma preparação — é o comportamento correto.

### 3. Dead-man's-switch: o teste que teria pego o caso real

Desligue o agendador **e** o container inteiro, como numa queda real:

```bash
docker compose stop pipeline        # ou desligue a VM
```

Anote a hora. O último ping foi a do último run verde; o healthchecks alerta quando
`último ping + 1 dia + 1 hora` passar.

| espera | o que prova |
|---|---|
| **~26 h** | o mecanismo funciona. Suficiente para dar a fatia como concluída |
| **1 semana** | que o alerta **persiste/reitera** e que você não o silencia sem perceber; é o teste honesto do critério original da F11 |

**Importante:** este alerta vem do healthchecks, **não** do ntfy do projeto. Confirme
que a integração do healthchecks (e-mail, ntfy, Telegram…) está apontando para um canal
que você lê — é o ponto mais fácil de esquecer.

Ao terminar: `docker compose start pipeline`; o próximo run verde deve fazer o check
voltar a **Up**.

## Fora de escopo

- Mudar código: se algo falhar, reabra a [F11](F11-observabilidade.md), como a F08b fez
  com as fatias que validou.

## Critério de aceite

1. O smoke test do item 1 chega ao celular e o check fica **Up**.
2. O run com falha do item 2 gera alerta no celular e deixa o check **Down**.
3. Com o container parado, o alerta de ausência chega em até ~26 h.
4. Você registra aqui, ao concluir, a data/hora de cada etapa e o canal em que o alerta
   apareceu — sem isso a fatia não está concluída.

## Registro de execução (24/09/2026, horários em UTC; Maceió = UTC-3)

Stack subida com `docker compose up -d --build` a partir de um warehouse herdado de
versão antiga (só uma VIEW `stg_caged_movimentacoes`, sem tabela física).

| hora | evento | resultado |
|---|---|---|
| 05:51 | `docker compose up -d --build` | `prefect-server` e `pipeline` no ar; deployment criado por `prefect deploy`; `./data` já com o dono do host (F08b item 4 ok) |
| 05:5x | smoke test: alerta "CAGED: teste F17" + ping | `notificar` e `ping_heartbeat` devolveram `True` (HTTP aceito) |
| 05:55 | run real via `prefect deployment run` | **falhou** em `dbt run` (`PermissionError: /dbt/logs/dbt.log`); hook enviou alerta "CAGED pipeline: Failed" e `/fail` |
| 06:00 | run manual reexecutado (após corrigir) | **verde**: ingeriu 202604-202607, 23/23 testes, 4 `.txt` apagados (1,7 GB), defasagem 55 dias, heartbeat de sucesso |
| 06:02 | run do cron das 03:00 (Maceió) sobreposto ao manual | **falhou**: `No files found ... CAGEDMOV202605.txt`; segundo alerta + `/fail` |
| 06:0x | duas execuções simultâneas após a correção | uma esperou (`AwaitingConcurrencySlot`), ambas verdes |

**Achados (todos corrigidos, reabrindo as fatias de origem):**

1. **`/dbt/logs/dbt.log` root-owned** (F07): o entrypoint só ajustava o dono do mount
   point; arquivos root herdados de containers antigos dentro de `dbt/` derrubavam o
   `dbt run`. Agora `docker-entrypoint.sh` faz `chown` de `dbt/logs`, `dbt/target` e
   `.user.yml`.
2. **Corrida entre dois runs** (F03/F07): sem limite de concorrência, um run apagava o
   `.txt` (`deletar_txt_extraido`) que o outro ia processar. `prefect.yaml` ganhou
   `concurrency_limit: 1` com `ENQUEUE`; `_transformar` também limpa `.txt` órfãos de
   competências já no warehouse.
3. **View legada da staging** (F11): consultada por `competencias_ja_ingeridas`, varreria
   GBs de `.txt`. Só tabela física conta agora (commit `ab3da37`).

O alerta de falha (item 2 do escopo) foi exercitado **duas vezes por falhas reais**, não
por simulação, e o heartbeat `/fail` acompanhou as duas.

**Confirmado pelo usuário (24/09/2026):** os alertas do smoke test e das duas falhas
chegaram ao celular. Itens 1 e 2 concluídos.

### Item 3 — container parado

- Último ping de sucesso: **06:04:06 UTC** (run `casual-swallow`, 24/09).
- `docker compose stop pipeline`: **06:13:55 UTC** (24/09). O `prefect-server` seguiu no ar.
- Alerta de ausência esperado: último ping + 1 dia + 1 h de tolerância =
  **~07:04 UTC de 25/09 (~04:04 em Maceió)**, pelo healthchecks, no canal configurado nele.
- Para encerrar o teste: `docker compose start pipeline`. O primeiro run verde volta a
  mandar ping e o check retorna a **Up**.

**Reexecução do item 3 (24/09/2026):** a pedido do usuário, o container foi religado, um
ping de sucesso foi enviado às **~06:20:35 UTC** e o `pipeline` foi parado novamente às
**06:20:36 UTC**. O prazo de espera passa a contar desse ping.

**Ao receber o alerta, registrar aqui:** hora em que chegou e em que canal.
Se passar de ~08:00 UTC de 25/09 sem alerta, o teste **falhou**: verifique a integração
do healthchecks (onde ele envia) antes de suspeitar do projeto.
