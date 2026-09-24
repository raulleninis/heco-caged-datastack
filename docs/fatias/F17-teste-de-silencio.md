# F17 · Teste de silêncio: provar que o alerta chega

| | |
|---|---|
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
