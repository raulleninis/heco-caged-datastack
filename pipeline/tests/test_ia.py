"""
Testes das proteções de gasto do boletim com IA (F19 parte 2). Nenhum chama a API: os
agentes usam FunctionModel, que devolve respostas com uso e custo controlados.

Rodar (a imagem precisa ter pydantic-ai-slim):
    docker compose run --rm --no-deps -v ./pipeline/tests:/app/tests \\
        --entrypoint python pipeline -m unittest discover -s /app/tests -v
"""

import json
import sys
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path

from pydantic_ai import Agent, ModelRetry, UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "flows"))

import ia  # noqa: E402

BARATO, CARO = "teste/barato", "teste/caro"
MODELOS_API = {"data": [
    # preços por token: barato = US$ 1/M entrada e US$ 5/M saída; caro = US$ 20/M saída
    {"id": BARATO, "pricing": {"prompt": "0.000001", "completion": "0.000005"}},
    {"id": CARO, "pricing": {"prompt": "0.000004", "completion": "0.00002"}},
]}


def resposta(custo: float | None = 0.01, entrada: int = 1000, saida: int = 200):
    def fn(msgs, info: AgentInfo):
        return ModelResponse(parts=[TextPart("ok")], usage=RequestUsage(input_tokens=entrada, output_tokens=saida),
                             provider_details={"cost": custo} if custo is not None else None)
    return fn


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self.tmp.name)
        self.cfg = ia.ConfigIA(api_key="sk-teste", modelos_permitidos=(BARATO, CARO),
                               orcamento_mensal_usd=Decimal("2"), preco_max_saida_usd_mtok=Decimal("15"),
                               pasta=self.pasta)
        self.precos = ia.Precos(self.pasta, baixar=lambda: MODELOS_API)
        self.registro = ia.RegistroCustos(self.pasta)

    def tearDown(self):
        self.tmp.cleanup()

    def execucao(self, modelos=None):
        return ia.Execucao(self.cfg, modelos or {"redator": BARATO}, precos=self.precos, registro=self.registro,
                           territorio="280480", competencia="202607")

    def linhas(self):
        return [json.loads(l) for l in self.registro.arquivo.read_text(encoding="utf-8").splitlines()]


class Modelos(Base):
    def test_modelo_fora_da_lista_e_recusado(self):
        with self.assertRaises(ia.ModeloNaoPermitido):
            self.execucao({"redator": "outro/modelo"})

    def test_modelo_acima_do_teto_de_preco_e_recusado(self):
        with self.assertRaises(ia.ModeloNaoPermitido):
            self.execucao({"redator": CARO})

    def test_papel_desconhecido_e_erro(self):
        with self.assertRaises(ValueError):
            self.execucao({"gerente": BARATO})

    def test_maximo_e_o_pior_caso_dos_limites(self):
        ex = self.execucao()
        # 120 mil × US$ 1/M + 20 mil × US$ 5/M
        self.assertEqual(ex.maximo, Decimal("0.22"))

    def test_modelo_openrouter_leva_os_limites_do_papel(self):
        m = ia.modelo_openrouter(self.cfg, BARATO, "redator")
        self.assertEqual(m.settings["max_tokens"], ia.LIMITES_PAPEL["redator"].max_tokens)
        self.assertEqual(m.settings["openrouter_usage"], {"include": True})
        sem_chave = ia.ConfigIA(**{**self.cfg.__dict__, "api_key": None})
        with self.assertRaises(RuntimeError):
            ia.modelo_openrouter(sem_chave, BARATO, "redator")


class Orcamento(Base):
    def test_execucao_que_nao_cabe_e_recusada_sem_chamar_o_modelo(self):
        self.registro.reservar("antiga", Decimal("1.90"))
        self.registro.encerrar("antiga", "ok")
        self.registro.chamada("antiga", custo_usd="1.90")
        chamadas = []

        def fn(msgs, info):
            chamadas.append(1)
            return resposta()(msgs, info)

        with self.assertRaises(ia.OrcamentoExcedido):
            with self.execucao() as ex:
                ex.rodar(Agent(FunctionModel(fn, model_name=BARATO)), "redator", "x")
        self.assertEqual(chamadas, [])

    def test_reserva_aberta_conta_pelo_maximo(self):
        self.registro.reservar("morta", Decimal("0.44"))
        self.registro.chamada("morta", custo_usd="0.05")
        self.assertEqual(self.registro.gasto_mes(), Decimal("0.44"))
        self.registro.encerrar("morta", "ok")
        self.assertEqual(self.registro.gasto_mes(), Decimal("0.05"))

    def test_outros_meses_nao_contam(self):
        self.registro.reservar("x", Decimal("1"))
        self.assertEqual(self.registro.gasto_mes("1999-01"), Decimal(0))


class Registro(Base):
    def test_custo_do_provedor_e_registrado_por_resposta(self):
        with self.execucao() as ex:
            saida = ex.rodar(Agent(FunctionModel(resposta(0.0123), model_name=BARATO)), "redator", "x")
        self.assertEqual(saida, "ok")
        tipos = [l["tipo"] for l in self.linhas()]
        self.assertEqual(tipos, ["reserva", "chamada", "encerramento"])
        chamada = self.linhas()[1]
        self.assertEqual((chamada["custo_usd"], chamada["custo_fonte"]), ("0.0123", "provedor"))
        self.assertEqual(self.registro.gasto_mes(), Decimal("0.0123"))

    def test_sem_custo_do_provedor_estima_pelos_tokens(self):
        with self.execucao() as ex:
            ex.rodar(Agent(FunctionModel(resposta(None, 1000, 200), model_name=BARATO)), "redator", "x")
        chamada = self.linhas()[1]
        # 1000 × 1e-6 + 200 × 5e-6
        self.assertEqual((Decimal(chamada["custo_usd"]), chamada["custo_fonte"]), (Decimal("0.002"), "estimado"))

    def test_rodar_fora_do_with_e_erro(self):
        with self.assertRaises(RuntimeError):
            self.execucao().rodar(Agent(FunctionModel(resposta(), model_name=BARATO)), "redator", "x")


class Limites(Base):
    def test_laco_de_novas_tentativas_para_no_limite_de_requisicoes(self):
        agente = Agent(FunctionModel(resposta(), model_name=BARATO), retries=50)

        @agente.output_validator
        def nunca_aceita(saida: str) -> str:
            raise ModelRetry("de novo")

        with self.assertRaises(UsageLimitExceeded):
            with self.execucao() as ex:
                ex.rodar(agente, "redator", "x")
        self.assertEqual(ex.uso.requests, ia.LIMITES_EXECUCAO["request_limit"])
        linhas = self.linhas()
        self.assertEqual(linhas[1]["custo_fonte"], "estimado")
        self.assertEqual(linhas[1]["motivo"], "limite de uso atingido")
        self.assertTrue(linhas[-1]["situacao"].startswith("erro"))

    def test_limite_e_compartilhado_entre_agentes(self):
        a = Agent(FunctionModel(resposta(), model_name=BARATO))
        with self.assertRaises(UsageLimitExceeded):
            with self.execucao({"analista": BARATO, "redator": BARATO}) as ex:
                for _ in range(ia.LIMITES_EXECUCAO["request_limit"]):
                    ex.rodar(a, "analista", "x")
                ex.rodar(a, "redator", "x")  # a 9ª requisição da execução

    def test_limite_de_tokens_de_saida(self):
        grande = Agent(FunctionModel(resposta(0.01, 100, ia.LIMITES_EXECUCAO["output_tokens_limit"] + 1),
                                     model_name=BARATO))
        with self.assertRaises(UsageLimitExceeded):
            with self.execucao() as ex:
                ex.rodar(grande, "redator", "x")


class PrecosTeste(Base):
    def test_sem_api_e_sem_copia_recusa(self):
        def falha():
            raise OSError("sem rede")

        with self.assertRaises(RuntimeError):
            ia.Precos(self.pasta / "vazia", baixar=falha).de(BARATO)

    def test_usa_copia_recente_e_recusa_copia_vencida(self):
        ia.Precos(self.pasta, baixar=lambda: MODELOS_API).de(BARATO)  # grava a cópia

        def falha():
            raise OSError("sem rede")

        self.assertEqual(ia.Precos(self.pasta, baixar=falha).de(BARATO)[1], Decimal("0.000005"))
        arq = self.pasta / "precos_openrouter.json"
        copia = json.loads(arq.read_text())
        copia["baixado_em"] = time.time() - 8 * 86400
        arq.write_text(json.dumps(copia))
        with self.assertRaises(RuntimeError):
            ia.Precos(self.pasta, baixar=falha).de(BARATO)

    def test_modelo_inexistente_na_openrouter(self):
        with self.assertRaises(ia.ModeloNaoPermitido):
            self.precos.de("nao/existe")


if __name__ == "__main__":
    unittest.main()
