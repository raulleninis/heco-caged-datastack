"""
Alertas e heartbeat do pipeline (F11).

Dois mecanismos, ambos configurados por variável de ambiente e ambos opcionais
(sem a variável, viram no-op com um aviso no log — o pipeline nunca deixa de
rodar por falta de canal de alerta):

- NTFY_URL: URL completa do tópico ntfy (ex.: https://ntfy.sh/meu-topico ou
  uma instância própria). Recebe o alerta ATIVO: falha do flow, silêncio
  (defasagem excedida), testes de plausibilidade em WARN, anomalia de volume.

- HEARTBEAT_URL: URL de um serviço dead-man's-switch (healthchecks.io ou
  equivalente). Recebe um ping ao fim de todo run bem-sucedido; o alerta vem
  da AUSÊNCIA do ping. É o único mecanismo externo ao que ele vigia: se o
  Prefect, o container ou a máquina inteira pararem, o alerta ainda sai —
  o que nenhum alerta interno consegue (foi assim que o pipeline ficou dois
  meses parado sem ninguém saber).

Falhar ao alertar nunca derruba o flow: o erro é logado e o run segue.
"""

import json
import logging
import os
import urllib.request

from prefect.exceptions import MissingContextError
from prefect.logging import get_run_logger

PRIORIDADES = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5}


def _logger():
    try:
        return get_run_logger()
    except MissingContextError:
        return logging.getLogger("alertas")


def notificar(titulo: str, mensagem: str, prioridade: str = "default") -> bool:
    """Envia um alerta ao ntfy. Devolve True se enviou."""
    logger = _logger()
    url = os.environ.get("NTFY_URL", "").strip()
    if not url:
        logger.warning(f"[alerta sem canal — NTFY_URL não definida] {titulo}: {mensagem}")
        return False

    base, _, topico = url.rstrip("/").rpartition("/")
    corpo = json.dumps({
        "topic": topico,
        "title": titulo,
        "message": mensagem,
        "priority": PRIORIDADES.get(prioridade, 3),
    }).encode()
    req = urllib.request.Request(base, data=corpo, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15).close()
    except Exception as e:  # noqa: BLE001 — alerta nunca derruba o flow
        logger.error(f"Falha ao enviar alerta ao ntfy ({e}): {titulo}")
        return False
    logger.info(f"Alerta enviado: {titulo}")
    return True


def ping_heartbeat(sucesso: bool = True) -> bool:
    """Ping no dead-man's-switch. Sem sucesso, usa o sufixo /fail
    (convenção do healthchecks.io: sinaliza falha explícita sem esperar o
    prazo estourar)."""
    logger = _logger()
    url = os.environ.get("HEARTBEAT_URL", "").strip()
    if not url:
        logger.warning("HEARTBEAT_URL não definida — sem alerta externo de silêncio.")
        return False
    if not sucesso:
        url = url.rstrip("/") + "/fail"
    try:
        urllib.request.urlopen(url, timeout=15).close()
    except Exception as e:  # noqa: BLE001
        logger.error(f"Falha no heartbeat ({e})")
        return False
    logger.info("Heartbeat enviado.")
    return True


def alerta_falha(flow, flow_run, state) -> None:
    """Hook on_failure/on_crashed dos flows: alerta ativo + heartbeat de falha."""
    try:
        detalhe = state.result(raise_on_failure=False)
    except Exception:  # noqa: BLE001
        detalhe = None
    msg = f"Flow '{flow.name}' terminou em {state.name}."
    if isinstance(detalhe, BaseException):
        msg += f" {type(detalhe).__name__}: {detalhe}"
    elif state.message:
        msg += f" {state.message}"
    notificar(f"CAGED pipeline: {state.name}", msg, prioridade="high")
    ping_heartbeat(sucesso=False)
