"""
Testes do boletim com IA (F19 parte 3): verificador de números e o fluxo analista → redator →
revisor, com modelos falsos (FunctionModel) que devolvem saídas roteirizadas. Sem rede.

Rodar (a imagem precisa ter pydantic-ai-slim):
    docker compose run --rm --no-deps -v ./pipeline/tests:/app/tests \\
        --entrypoint python pipeline -m unittest discover -s /app/tests -v
"""

import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "flows"))

import boletim_ia  # noqa: E402
import ia  # noqa: E402
from verificador import verificar_texto  # noqa: E402

NUMEROS = {
    "panorama.saldo": {"valor": -83, "unidade": "vinculos", "descricao": ""},
    "panorama.estoque": {"valor": 25439, "unidade": "vinculos", "descricao": ""},
    "panorama.taxa_mes": {"valor": -0.33, "unidade": "pct", "descricao": ""},
    "salario.mediana": {"valor": 1661.0, "unidade": "brl", "descricao": ""},
}
FATOS = {"territorio": {"codigo": "280480", "nome": "Município"}, "competencia": "202607", "hash": "a" * 64,
         "provisorio": True, "gatilhos": [], "numeros": NUMEROS}
REDATOR, REVISOR = "teste/redator", "teste/revisor"


class Verificador(unittest.TestCase):
    def test_aceita_formatos_sinal_e_arredondamento(self):
        texto = ("Saldo de −83 vínculos (queda de 83), estoque de 25.439, ou 25,4 mil. Variação de -0,33%, "
                 "cerca de 0,3%. Mediana de R$ 1.661,00 (R$ 1.661). Em 2025, nos 12 meses, três hipóteses.")
        self.assertEqual(verificar_texto(texto, NUMEROS), [])

    def test_recusa_numero_inventado_ou_derivado(self):
        texto = "Saldo de 84 vínculos, 0,5% no mês, R$ 1.700 de mediana e 30 mil de estoque."
        achados = [p["numero"] for p in verificar_texto(texto, NUMEROS)]
        self.assertEqual(achados, ["84", "0,5", "1.700", "30 mil"])

    def test_sinaliza_forma_juridica_de_empresa(self):
        tipos = [p["tipo"] for p in verificar_texto("Demissões na Empresa X LTDA.", NUMEROS)]
        self.assertEqual(tipos, ["possivel_identificacao"])


def analise(ids=("panorama.saldo",)):
    return {"destaques": [{"tema": "saldo", "ids": list(ids), "por_que": "gatilho"}],
            "desagregacoes": [], "hipoteses_a_investigar": []}


def boletim(numero="−83"):
    return {"titulo": "Boletim", "sintese": f"Saldo de {numero} vínculos.",
            "secoes": [{"titulo": "Panorama", "paragrafos": ["Estoque de 25.439."]}],
            "hipoteses": [], "limitacoes": ["Provisório."]}


def parecer(grave=False):
    return {"resumo": "ok", "problemas": [{"tipo": "causalidade", "gravidade": "grave" if grave else "menor",
                                           "trecho": "x", "sugestao": "y"}]}


class Roteiro:
    """Modelos falsos: cada papel devolve a próxima saída da sua fila, como resultado estruturado."""

    def __init__(self, **filas):
        self.filas = {p: list(v) for p, v in filas.items()}
        self.chamadas = {p: 0 for p in filas}

    def criar_modelo(self, papel):
        def fn(msgs, info: AgentInfo):
            self.chamadas[papel] += 1
            fila = self.filas[papel]
            saida = fila.pop(0) if len(fila) > 1 else fila[0]
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, saida)],
                                 usage=RequestUsage(input_tokens=5000, output_tokens=800),
                                 provider_details={"cost": 0.001})
        return FunctionModel(fn, model_name=REDATOR if papel == "redator" else REVISOR)


class Fluxo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self.tmp.name)
        self.cfg = ia.ConfigIA(api_key="sk", modelos_permitidos=(REDATOR, REVISOR), orcamento_mensal_usd=Decimal("2"),
                               preco_max_saida_usd_mtok=Decimal("15"), pasta=self.pasta)
        precos = {"data": [{"id": m, "pricing": {"prompt": "0.000001", "completion": "0.000004"}} for m in (REDATOR, REVISOR)]}
        self.precos = ia.Precos(self.pasta, baixar=lambda: precos)
        self.registro = ia.RegistroCustos(self.pasta)
        self.modelos = {"analista": REVISOR, "redator": REDATOR, "revisor": REVISOR}

    def tearDown(self):
        self.tmp.cleanup()

    def gerar(self, roteiro, **kw):
        return boletim_ia.gerar(FATOS, self.cfg, self.modelos, criar_modelo=roteiro.criar_modelo,
                                precos=self.precos, registro=self.registro, **kw)

    def test_fluxo_feliz_fica_aguardando_aprovacao(self):
        r = Roteiro(analista=[analise()], redator=[boletim()], revisor=[parecer()])
        res = self.gerar(r)
        self.assertEqual(res["situacao"], "aguardando_aprovacao")
        self.assertEqual(res["versoes_do_redator"], 1)
        self.assertEqual(r.chamadas, {"analista": 1, "redator": 1, "revisor": 1})
        pasta = Path(res["pasta"])
        self.assertTrue((pasta / "boletim.md").exists() and (pasta / "fatos.json").exists())
        linhas = [json.loads(l) for l in self.registro.arquivo.read_text().splitlines()]
        self.assertEqual([l["tipo"] for l in linhas], ["reserva", "chamada", "chamada", "chamada", "encerramento"])

    def test_numero_inventado_gera_uma_nova_tentativa(self):
        r = Roteiro(analista=[analise()], redator=[boletim("−90"), boletim()], revisor=[parecer()])
        res = self.gerar(r)
        self.assertEqual(r.chamadas["redator"], 2)
        self.assertEqual(res["situacao"], "aguardando_aprovacao")

    def test_numero_inventado_insistente_vai_reprovado_para_revisao_humana(self):
        r = Roteiro(analista=[analise()], redator=[boletim("−90")], revisor=[parecer()])
        res = self.gerar(r)
        self.assertEqual(r.chamadas["redator"], 2)  # 1 + 1 nova tentativa, sem laço
        self.assertEqual(res["situacao"], "reprovado_no_verificador")
        self.assertEqual([p["numero"] for p in res["verificador"]], ["−90"])

    def test_problema_grave_do_revisor_gera_segunda_versao(self):
        r = Roteiro(analista=[analise()], redator=[boletim()], revisor=[parecer(grave=True)])
        res = self.gerar(r)
        self.assertEqual(res["versoes_do_redator"], 2)
        self.assertEqual(r.chamadas["redator"], 2)
        self.assertEqual(r.chamadas["revisor"], 1)  # não revisa de novo

    def test_ids_inexistentes_no_analista_geram_nova_tentativa(self):
        r = Roteiro(analista=[analise(["nao.existe"]), analise()], redator=[boletim()], revisor=[parecer()])
        res = self.gerar(r)
        self.assertEqual(r.chamadas["analista"], 2)
        self.assertEqual(res["analise"]["destaques"][0]["ids"], ["panorama.saldo"])

    def test_mesmos_fatos_reaproveitam_sem_chamar_modelos(self):
        self.gerar(Roteiro(analista=[analise()], redator=[boletim()], revisor=[parecer()]))
        r2 = Roteiro(analista=[analise()], redator=[boletim()], revisor=[parecer()])
        res = self.gerar(r2)
        self.assertTrue(res["reaproveitado"])
        self.assertEqual(r2.chamadas, {"analista": 0, "redator": 0, "revisor": 0})
        self.gerar(r2, refazer=True)
        self.assertEqual(r2.chamadas["redator"], 1)

    def test_pior_caso_cabe_no_limite_de_requisicoes(self):
        # tudo dá errado uma vez: analista 2 + redator 2 + revisor 1 + redator 2 = 7 ≤ 8
        r = Roteiro(analista=[analise(["x"]), analise()], redator=[boletim("−90")], revisor=[parecer(grave=True)])
        res = self.gerar(r)
        self.assertEqual(sum(r.chamadas.values()), 7)
        self.assertEqual(res["situacao"], "reprovado_no_verificador")

    def test_modelos_do_ambiente(self):
        m = boletim_ia.modelos_do_ambiente(self.cfg)
        self.assertEqual((m["redator"], m["revisor"], m["analista"]), (REDATOR, REVISOR, REVISOR))
        vazio = ia.ConfigIA(**{**self.cfg.__dict__, "modelos_permitidos": ()})
        with self.assertRaises(RuntimeError):
            boletim_ia.modelos_do_ambiente(vazio)


if __name__ == "__main__":
    unittest.main()
