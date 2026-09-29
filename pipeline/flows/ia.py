"""
Cliente de LLM do boletim com IA (F19 parte 2): OpenRouter via PydanticAI, com as proteções
contra gasto. Os agentes (parte 3) só rodam através de uma `Execucao`.

Camadas (docs/fatias/F19-boletim-com-ia.md, "Proteções contra gasto"):

- modelo: só os de IA_MODELOS_PERMITIDOS, e com preço de saída até IA_PRECO_MAX_SAIDA_USD_MTOK;
- chamada: `max_tokens`, tempo limite e esforço de raciocínio fixos por papel (LIMITES_PAPEL);
- execução: um `UsageLimits` e um contador (`RunUsage`) COMPARTILHADOS por todos os agentes da
  execução: requisições, chamadas de ferramenta e tokens de entrada e saída;
- mês: antes de começar, a execução RESERVA o seu custo máximo possível (limites de tokens ×
  preço do modelo mais caro da execução) e é recusada se gasto do mês + reserva passar de
  IA_ORCAMENTO_MENSAL_USD. Depois de cada chamada, grava o custo real informado pela OpenRouter.
  Uma reserva sem encerramento (processo morto no meio) continua contando pelo máximo.

Por que não o `cost_limit` do PydanticAI: ele calcula o custo por uma tabela de preços embutida
(genai-prices) e, para um modelo que ela não conhece, não aplica o limite (só avisa). O custo
real da OpenRouter chega em `provider_details['cost']`, fora do contador que o `cost_limit` vê.
Como os limites de TOKENS o PydanticAI aplica de fato, a reserva pelo pior caso é um teto real.

O limite de crédito da chave na OpenRouter (mesmo valor do orçamento) é o teto final, que vale
mesmo se este código falhar.
"""

import fcntl
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from pydantic_ai import Agent, UsageLimitExceeded
from pydantic_ai.messages import ModelResponse
from pydantic_ai.usage import RunUsage, UsageLimits

URL_MODELOS = "https://openrouter.ai/api/v1/models"
URL_ENDPOINTS = "https://openrouter.ai/api/v1/models/{}/endpoints"
URL_DECISOES = "https://openrouter.ai/api/alpha/decisions"

# Modelos de decisão (Jev): endpoint próprio, sem saída de texto. Teto de chamadas e de tamanho
# por execução; o contexto do jev-1.13 é de 32 mil tokens.
MAX_DECISOES = 60
ENTRADA_MAX_DECISAO = 30_000


class OrcamentoExcedido(RuntimeError):
    """A execução foi recusada antes de qualquer chamada: não cabe no orçamento do mês."""


class ModeloNaoPermitido(ValueError):
    pass


# Modelos que devolvem decisões tipadas, não texto (ex.: typesafe/jev-1.13): só servem ao papel
# "juiz", nunca aos papéis que redigem.
PREFIXOS_MODELOS_DE_DECISAO = ("typesafe/",)


def e_modelo_de_decisao(modelo: str) -> bool:
    return modelo.startswith(PREFIXOS_MODELOS_DE_DECISAO)


class LimiteDeDecisoes(RuntimeError):
    """Teto de chamadas (ou de tamanho) do modelo de decisão atingido nesta execução."""


@dataclass(frozen=True)
class LimitesPapel:
    max_tokens: int          # saída máxima por chamada (inclui raciocínio)
    timeout: float           # segundos por chamada
    raciocinio: str | None   # esforço de raciocínio pedido à OpenRouter; None = não pedir


# Por papel. O redator escreve 3 a 4 páginas (~3 mil tokens) e pode raciocinar um pouco.
LIMITES_PAPEL = {
    "analista": LimitesPapel(max_tokens=2_000, timeout=90, raciocinio="low"),
    "pesquisador": LimitesPapel(max_tokens=3_000, timeout=120, raciocinio="low"),
    "redator": LimitesPapel(max_tokens=8_000, timeout=180, raciocinio="low"),
    "revisor": LimitesPapel(max_tokens=3_000, timeout=120, raciocinio="low"),
    # conselheiro (3b-2): modelo mais capaz, consultado no máximo 2 vezes, resposta curta
    "advisor": LimitesPapel(max_tokens=1_200, timeout=120, raciocinio="low"),
    # modelo de decisão (Jev): não gera texto; limites próprios em MAX_DECISOES
    "juiz": LimitesPapel(max_tokens=0, timeout=30, raciocinio=None),
}

# Por execução (todos os agentes juntos). Uma execução normal: ~35 mil tokens de entrada e ~8
# mil de saída em 4 a 6 requisições.
LIMITES_EXECUCAO = {
    # pior caso do boletim com IA (3b-2): analista 2 + advisor 2 + redator 2 + revisor 1 + redator 2 = 9
    "request_limit": 10,
    "tool_calls_limit": 6,
    "input_tokens_limit": 120_000,
    "output_tokens_limit": 20_000,
}


@dataclass(frozen=True)
class ConfigIA:
    api_key: str | None
    modelos_permitidos: tuple[str, ...]
    orcamento_mensal_usd: Decimal
    preco_max_saida_usd_mtok: Decimal
    pasta: Path  # registro de custos, cache de preços e resultados

    @classmethod
    def do_ambiente(cls) -> "ConfigIA":
        return cls(
            api_key=os.environ.get("OPENROUTER_API_KEY") or None,
            modelos_permitidos=tuple(
                m.strip() for m in os.environ.get("IA_MODELOS_PERMITIDOS", "").split(",") if m.strip()
            ),
            orcamento_mensal_usd=Decimal(os.environ.get("IA_ORCAMENTO_MENSAL_USD", "2")),
            preco_max_saida_usd_mtok=Decimal(os.environ.get("IA_PRECO_MAX_SAIDA_USD_MTOK", "15")),
            pasta=Path(os.environ.get("IA_DIR", "/data/ia")),
        )


# --- preços -----------------------------------------------------------------------------------

def _baixar_modelos() -> dict:
    req = urllib.request.Request(URL_MODELOS, headers={"User-Agent": "boletim-caged"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _baixar_endpoints(modelo: str) -> dict:
    req = urllib.request.Request(URL_ENDPOINTS.format(modelo), headers={"User-Agent": "boletim-caged"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _preco(pricing: dict) -> tuple[Decimal, Decimal] | None:
    """(entrada, saída) por token; None se ausente ou VARIÁVEL (a OpenRouter devolve −1 para
    roteadores que escolhem o modelo a cada chamada: sem preço fixo, não há pior caso)."""
    try:
        entrada, saida = Decimal(str(pricing["prompt"])), Decimal(str(pricing["completion"]))
    except (KeyError, TypeError, ArithmeticError):
        return None
    return None if entrada < 0 or saida < 0 else (entrada, saida)


def _post_decisoes(api_key: str, corpo: dict, timeout: float) -> dict:
    req = urllib.request.Request(URL_DECISOES, data=json.dumps(corpo).encode(), headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": "boletim-caged"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Decisões da OpenRouter: HTTP {e.code}: {e.read()[:300]!r}") from e


class Precos:
    """Preço por token (USD) de cada modelo, da API pública da OpenRouter (sem chave).

    Guarda uma cópia em disco. Se a API falhar, usa a cópia de até `validade_dias`; sem preço
    confiável, NÃO roda (falha fechado): gastar sem saber quanto custa é o que se quer evitar."""

    def __init__(self, pasta: Path, baixar=_baixar_modelos, validade_dias: int = 7,
                 baixar_endpoints=_baixar_endpoints):
        self.arquivo = pasta / "precos_openrouter.json"
        self.baixar = baixar
        self.baixar_endpoints = baixar_endpoints
        self.validade = validade_dias * 86400
        self._tabela: dict[str, tuple[Decimal, Decimal]] | None = None

    def _carregar(self) -> dict[str, tuple[Decimal, Decimal]]:
        try:
            dados = self.baixar()
            self.arquivo.parent.mkdir(parents=True, exist_ok=True)
            self.arquivo.write_text(json.dumps({"baixado_em": time.time(), "dados": dados}), encoding="utf-8")
        except Exception as e:
            if not self.arquivo.exists():
                raise RuntimeError(f"Sem preços da OpenRouter ({e}) e sem cópia local: execução recusada.") from e
            copia = json.loads(self.arquivo.read_text(encoding="utf-8"))
            if time.time() - copia["baixado_em"] > self.validade:
                raise RuntimeError(f"Sem preços da OpenRouter ({e}) e a cópia local está vencida: execução recusada.") from e
            dados = copia["dados"]
        tabela = {}
        for m in dados["data"]:
            preco = _preco(m.get("pricing") or {})
            if preco:
                tabela[m["id"]] = preco
        return tabela

    def de(self, modelo: str) -> tuple[Decimal, Decimal]:
        """(entrada, saída) em USD por token."""
        if self._tabela is None:
            self._tabela = self._carregar()
        if modelo not in self._tabela:
            # Alguns modelos (ex.: typesafe/jev-1.13) não aparecem na listagem geral; o preço
            # vem da consulta pelo id.
            try:
                pontos = self.baixar_endpoints(modelo)["data"]["endpoints"]
                preco = _preco(pontos[0]["pricing"]) if pontos else None
            except Exception:
                preco = None
            if not preco:
                raise ModeloNaoPermitido(f"Modelo {modelo} não existe na OpenRouter, está sem preço ou tem preço variável.")
            self._tabela[modelo] = preco
        return self._tabela[modelo]


# --- registro de custos -------------------------------------------------------------------------

class RegistroCustos:
    """Registro append-only (JSONL) de reservas, chamadas e encerramentos. É dele que sai o
    gasto do mês: chamadas das execuções encerradas + máximo(reserva, chamadas) das abertas."""

    def __init__(self, pasta: Path):
        self.arquivo = pasta / "custos.jsonl"
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        self.arquivo.touch(exist_ok=True)

    def _gravar(self, registro: dict) -> None:
        registro = {"quando": datetime.now(timezone.utc).isoformat(timespec="seconds"), **registro}
        with self.arquivo.open("a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(json.dumps(registro, ensure_ascii=False, default=str) + "\n")

    def _linhas(self) -> list[dict]:
        with self.arquivo.open(encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            return [json.loads(l) for l in f if l.strip()]

    def gasto_mes(self, mes: str | None = None) -> Decimal:
        mes = mes or datetime.now(timezone.utc).strftime("%Y-%m")
        reservas, chamadas, encerradas = {}, {}, set()
        for r in self._linhas():
            if not r["quando"].startswith(mes):
                continue
            ex = r["execucao"]
            if r["tipo"] == "reserva":
                reservas[ex] = Decimal(str(r["valor_usd"]))
            elif r["tipo"] == "chamada":
                chamadas[ex] = chamadas.get(ex, Decimal(0)) + Decimal(str(r["custo_usd"]))
            elif r["tipo"] == "encerramento":
                encerradas.add(ex)
        total = Decimal(0)
        for ex in set(reservas) | set(chamadas):
            gasto = chamadas.get(ex, Decimal(0))
            total += gasto if ex in encerradas else max(gasto, reservas.get(ex, Decimal(0)))
        return total

    def reservar(self, execucao: str, valor: Decimal, **contexto) -> None:
        self._gravar({"tipo": "reserva", "execucao": execucao, "valor_usd": str(valor), **contexto})

    def chamada(self, execucao: str, **dados) -> None:
        self._gravar({"tipo": "chamada", "execucao": execucao, **dados})

    def encerrar(self, execucao: str, situacao: str) -> None:
        self._gravar({"tipo": "encerramento", "execucao": execucao, "situacao": situacao})


# --- modelo e execução ---------------------------------------------------------------------------

def modelo_openrouter(cfg: ConfigIA, nome: str, papel: str):
    """O modelo da OpenRouter para um papel, com os limites de chamada. Só depois de a
    Execucao ter validado o nome e o preço."""
    from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings
    from pydantic_ai.providers.openrouter import OpenRouterProvider

    if not cfg.api_key:
        raise RuntimeError("OPENROUTER_API_KEY ausente no ambiente.")
    lim = LIMITES_PAPEL[papel]
    settings = OpenRouterModelSettings(
        max_tokens=lim.max_tokens,
        timeout=lim.timeout,
        temperature=0.2,
        openrouter_usage={"include": True},  # a resposta traz o custo real
    )
    if lim.raciocinio:
        settings["openrouter_reasoning"] = {"effort": lim.raciocinio}
    provider = OpenRouterProvider(api_key=cfg.api_key, app_title="Boletim CAGED")
    return OpenRouterModel(nome, provider=provider, settings=settings)


class Execucao:
    """Uma execução do boletim com IA: valida modelos e preços, reserva o pior caso no
    orçamento e roda os agentes com limites e contador compartilhados. Use com `with`:

        with Execucao(cfg, {"redator": "anthropic/claude-sonnet-5.5", ...}, territorio=..., competencia=...) as ex:
            texto = ex.rodar(agente_redator, "redator", prompt)
    """

    def __init__(self, cfg: ConfigIA, modelos: dict[str, str], *, precos: Precos | None = None,
                 registro: RegistroCustos | None = None, **contexto):
        desconhecidos = set(modelos) - set(LIMITES_PAPEL)
        if desconhecidos:
            raise ValueError(f"Papéis desconhecidos: {sorted(desconhecidos)}")
        self.cfg, self.modelos, self.contexto = cfg, modelos, contexto
        self.precos = precos or Precos(cfg.pasta)
        self.registro = registro or RegistroCustos(cfg.pasta)
        self.id = uuid.uuid4().hex[:12]
        self.limites = UsageLimits(**LIMITES_EXECUCAO)
        self.uso = RunUsage()
        self.maximo = self._validar_e_calcular_maximo()
        self._aberta = False
        self.decisoes = 0
        self.post_decisoes = _post_decisoes

    def _validar_e_calcular_maximo(self) -> Decimal:
        pior_entrada = pior_saida = Decimal(0)
        for papel, nome in self.modelos.items():
            if nome not in self.cfg.modelos_permitidos:
                raise ModeloNaoPermitido(f"{nome} ({papel}) não está em IA_MODELOS_PERMITIDOS.")
            entrada, saida = self.precos.de(nome)
            if saida * 1_000_000 > self.cfg.preco_max_saida_usd_mtok:
                raise ModeloNaoPermitido(
                    f"{nome}: US$ {saida * 1_000_000:.2f}/M tokens de saída, acima do teto "
                    f"IA_PRECO_MAX_SAIDA_USD_MTOK={self.cfg.preco_max_saida_usd_mtok}.")
            if papel == "juiz":
                continue  # modelo de decisão: pior caso próprio, abaixo
            pior_entrada, pior_saida = max(pior_entrada, entrada), max(pior_saida, saida)
        # Pior caso: todos os tokens permitidos, ao preço do modelo mais caro da execução...
        maximo = (LIMITES_EXECUCAO["input_tokens_limit"] * pior_entrada
                  + LIMITES_EXECUCAO["output_tokens_limit"] * pior_saida)
        # ...mais todas as decisões permitidas, cada uma no tamanho máximo.
        if "juiz" in self.modelos:
            entrada, saida = self.precos.de(self.modelos["juiz"])
            maximo += MAX_DECISOES * ENTRADA_MAX_DECISAO * entrada + MAX_DECISOES * 1_000 * saida
        return maximo

    def __enter__(self) -> "Execucao":
        gasto = self.registro.gasto_mes()
        if gasto + self.maximo > self.cfg.orcamento_mensal_usd:
            raise OrcamentoExcedido(
                f"Gasto do mês US$ {gasto:.4f} + máximo desta execução US$ {self.maximo:.4f} passa do "
                f"orçamento de US$ {self.cfg.orcamento_mensal_usd}. Nenhuma chamada foi feita.")
        self.registro.reservar(self.id, self.maximo, modelos=self.modelos, **self.contexto)
        self._aberta = True
        return self

    def __exit__(self, tipo, exc, tb) -> None:
        if self._aberta:
            self.registro.encerrar(self.id, "ok" if tipo is None else f"erro: {tipo.__name__}")
            self._aberta = False

    def rodar(self, agente: Agent, papel: str, prompt: str, **kw):
        """Roda um agente dentro dos limites da execução e registra o custo de cada resposta.
        Devolve o `output` do agente. UsageLimitExceeded é registrado e repassado."""
        if not self._aberta:
            raise RuntimeError("Execucao.rodar fora do bloco `with`.")
        if papel not in self.modelos:
            raise ValueError(f"Papel {papel} sem modelo nesta execução.")
        antes = (self.uso.input_tokens, self.uso.output_tokens, self.uso.requests)
        try:
            resultado = agente.run_sync(prompt, usage=self.uso, usage_limits=self.limites, **kw)
        except UsageLimitExceeded:
            self._registrar_estimado(papel, antes, "limite de uso atingido")
            raise
        except Exception:
            self._registrar_estimado(papel, antes, "erro")
            raise
        for msg in resultado.new_messages():
            if isinstance(msg, ModelResponse):
                self._registrar_resposta(papel, msg)
        return resultado.output

    def _registrar_resposta(self, papel: str, msg: ModelResponse) -> None:
        entrada, saida = self.precos.de(self.modelos[papel])
        custo = (msg.provider_details or {}).get("cost")
        fonte = "provedor"
        if custo is None:
            custo = msg.usage.input_tokens * entrada + msg.usage.output_tokens * saida
            fonte = "estimado"
        self.registro.chamada(
            self.id, papel=papel, modelo=self.modelos[papel], tokens_entrada=msg.usage.input_tokens,
            tokens_saida=msg.usage.output_tokens, custo_usd=str(custo), custo_fonte=fonte, **self.contexto)

    def _registrar_estimado(self, papel: str, antes: tuple, motivo: str) -> None:
        """Sem o resultado (exceção no meio), estima pelo que o contador compartilhado andou."""
        d_in = self.uso.input_tokens - antes[0]
        d_out = self.uso.output_tokens - antes[1]
        if not (d_in or d_out or self.uso.requests - antes[2]):
            return
        entrada, saida = self.precos.de(self.modelos[papel])
        self.registro.chamada(
            self.id, papel=papel, modelo=self.modelos[papel], tokens_entrada=d_in, tokens_saida=d_out,
            custo_usd=str(d_in * entrada + d_out * saida), custo_fonte="estimado", motivo=motivo, **self.contexto)

    def decidir(self, estado: dict, perguntas: dict) -> dict:
        """Uma chamada ao modelo de decisão do papel "juiz" (endpoint /api/alpha/decisions).
        Devolve `answers` (probabilidades por pergunta). Registra o custo real da resposta.
        Recusa antes de chamar se passar do teto de chamadas ou do tamanho máximo."""
        if not self._aberta:
            raise RuntimeError("Execucao.decidir fora do bloco `with`.")
        if "juiz" not in self.modelos:
            raise ValueError("Esta execução não tem modelo de decisão (papel 'juiz').")
        if self.decisoes >= MAX_DECISOES:
            raise LimiteDeDecisoes(f"Teto de {MAX_DECISOES} decisões por execução atingido.")
        corpo = {"model": self.modelos["juiz"], "state": estado, "questions": perguntas}
        estimativa = len(json.dumps(corpo, ensure_ascii=False)) // 3  # ~3 caracteres por token
        if estimativa > ENTRADA_MAX_DECISAO:
            raise LimiteDeDecisoes(f"Entrada de ~{estimativa} tokens passa do máximo de {ENTRADA_MAX_DECISAO}.")
        self.decisoes += 1
        resposta = self.post_decisoes(self.cfg.api_key, corpo, LIMITES_PAPEL["juiz"].timeout)
        uso = resposta.get("usage") or {}
        entrada, saida = self.precos.de(self.modelos["juiz"])
        custo, fonte = uso.get("cost"), "provedor"
        if custo is None:
            custo, fonte = uso.get("input_tokens", estimativa) * entrada + uso.get("output_tokens", 0) * saida, "estimado"
        self.registro.chamada(self.id, papel="juiz", modelo=self.modelos["juiz"],
                              tokens_entrada=uso.get("input_tokens"), tokens_saida=uso.get("output_tokens"),
                              custo_usd=str(custo), custo_fonte=fonte, **self.contexto)
        return resposta.get("answers") or {}
