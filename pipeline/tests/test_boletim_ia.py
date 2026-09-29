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
    "perfil.faixa_etaria.18_a_24.admissoes": {"valor": 306, "unidade": "vinculos", "descricao": ""},
}
FATOS = {"territorio": {"codigo": "280480", "nome": "Município"}, "competencia": "202607", "hash": "a" * 64,
         "provisorio": True, "gatilhos": [], "numeros": NUMEROS,
         "rotulos": {"competencia": "julho de 2026", "ano_anterior": "julho de 2025", "mes_anterior": "junho de 2026"},
         "setorial": {"grupamentos": {"Serviços": {"saldo": {"valor": -90}, "estoque": {"valor": 10907}}}, "destaques": ["Serviços"]},
         "comparacao": {"territorio": {"nome": "Município", "saldo": {"valor": -83}, "estoque": {"valor": 25439},
                                       "taxa_mes": {"valor": -0.33}, "taxa_12_meses": {"valor": 0.75}},
                        "regioes": [], "uf": None},
         "perfil": {"faixa_etaria": {"18 a 24": {"admissoes": {"valor": 306}, "saldo": {"valor": -3}}}}}
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

    def test_datas_nao_sao_dado(self):
        self.assertEqual(verificar_texto("Em 20 de setembro e em 25/09/2026, e no 1º de julho.", NUMEROS), [])
        self.assertEqual([p["numero"] for p in verificar_texto("Foram 20 vagas.", NUMEROS)], ["20"])

    def test_numero_de_rotulo_so_vale_na_posicao_do_rotulo(self):
        rotulos = ["18 a 24", "65 ou mais", "Até 17"]
        ok = "Na faixa de 18 a 24 anos e na de 65 anos ou mais, e até 17 anos."
        self.assertEqual(verificar_texto(ok, NUMEROS, rotulos), [])
        self.assertEqual([p["numero"] for p in verificar_texto("Saldo de 24 vínculos.", NUMEROS, rotulos)], ["24"])

    def test_avisos_de_estilo(self):
        from verificador import avisos_de_estilo
        motivos = " | ".join(a["motivo"] for a in avisos_de_estilo(
            "Vale ressaltar a queda — de 0,3% — no mesmo mês do ano anterior. Dado provisório. Outro provisório."))
        for esperado in ("travessão", "vale ressaltar", "2 casas", "nome do mês", "provisórios"):
            self.assertIn(esperado, motivos)

    def test_separador_de_milhar_sem_mexer_em_anos(self):
        from verificador import formatar_milhares
        self.assertEqual(formatar_milhares("Estoque de 25439 em 2025, mediana de R$ 1661,00 e 1060 admissões."),
                         "Estoque de 25.439 em 2025, mediana de R$ 1.661,00 e 1.060 admissões.")
        self.assertEqual(formatar_milhares("Já formatado: 25.439 e -0,33%."), "Já formatado: 25.439 e -0,33%.")

    def test_sinal_de_menos_no_texto_gera_aviso(self):
        from verificador import avisos_de_estilo
        self.assertIn("sinal de menos", avisos_de_estilo("O saldo de -83 vínculos.")[0]["motivo"])

    def test_sinaliza_forma_juridica_de_empresa(self):
        tipos = [p["tipo"] for p in verificar_texto("Demissões na Empresa X LTDA.", NUMEROS)]
        self.assertEqual(tipos, ["possivel_identificacao"])


def analise(ids=("panorama.saldo",)):
    return {"destaques": [{"tema": "saldo", "ids": list(ids), "por_que": "gatilho"}],
            "desagregacoes": [], "hipoteses_a_investigar": []}


def boletim(numero="−83"):
    return {"titulo": "Boletim", "sintese": f"Saldo de {numero} vínculos.",
            "panorama": ["Estoque de 25.439."], "setores": ["Serviços concentrou a perda."],
            "contexto_regional": ["Taxa de -0,33% no mês."], "perfil_e_remuneracao": ["Na faixa de 18 a 24 anos, 306 admissões."],
            "pontos_de_atencao": ["Acompanhar Serviços."], "nota_metodologica": "Dados provisórios."}


def parecer(grave=False):
    return {"resumo": "ok", "problemas": [{"tipo": "causalidade", "gravidade": "grave" if grave else "menor",
                                           "trecho": "x", "sugestao": "y"}]}


class Roteiro:
    """Modelos falsos: cada papel devolve a próxima saída da sua fila, como resultado estruturado."""

    def __init__(self, **filas):
        self.filas = {p: list(v) for p, v in filas.items()}
        self.chamadas = {p: 0 for p in filas}
        self.prompts = {p: [] for p in filas}

    def criar_modelo(self, papel):
        def fn(msgs, info: AgentInfo):
            self.chamadas[papel] += 1
            self.prompts[papel].append(str(msgs))
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
        md = (pasta / "boletim.md").read_text()
        # tabelas geradas por código a partir dos fatos, depois do texto
        self.assertIn("| Serviços | -90 |", md)
        self.assertIn("| Município | -83 | 25.439 | -0,33% | 0,75% |", md)
        self.assertEqual(res["rejeicoes_do_verificador"], [[]])
        linhas = [json.loads(l) for l in self.registro.arquivo.read_text().splitlines()]
        self.assertEqual([l["tipo"] for l in linhas], ["reserva", "chamada", "chamada", "chamada", "encerramento"])

    def test_numero_inventado_gera_uma_nova_tentativa(self):
        r = Roteiro(analista=[analise()], redator=[boletim("−91"), boletim()], revisor=[parecer()])
        res = self.gerar(r)
        self.assertEqual(r.chamadas["redator"], 2)
        self.assertEqual(res["situacao"], "aguardando_aprovacao")
        self.assertEqual(res["rejeicoes_do_verificador"], [["−91"], []])

    def test_modelo_de_decisao_nao_redige(self):
        with self.assertRaises(ValueError):
            boletim_ia.gerar(FATOS, self.cfg, {**self.modelos, "redator": "typesafe/jev-1.13"},
                             criar_modelo=Roteiro(analista=[analise()], redator=[boletim()], revisor=[parecer()]).criar_modelo,
                             precos=self.precos, registro=self.registro)

    def test_numero_inventado_insistente_vai_reprovado_para_revisao_humana(self):
        r = Roteiro(analista=[analise()], redator=[boletim("−91")], revisor=[parecer()])
        res = self.gerar(r)
        self.assertEqual(r.chamadas["redator"], 2)  # 1 + 1 nova tentativa, sem laço
        self.assertEqual(res["situacao"], "reprovado_no_verificador")
        self.assertEqual([p["numero"] for p in res["verificador"]], ["−91"])

    def test_problema_grave_do_revisor_gera_segunda_versao(self):
        r = Roteiro(analista=[analise()], redator=[boletim()], revisor=[parecer(grave=True)])
        res = self.gerar(r)
        self.assertEqual(res["versoes_do_redator"], 2)
        self.assertEqual(r.chamadas["redator"], 2)
        self.assertEqual(r.chamadas["revisor"], 1)  # não revisa de novo

    def test_muitos_avisos_de_estilo_geram_segunda_versao(self):
        feio = {**boletim(), "sintese": "Vale ressaltar o saldo de -83 — no mesmo mês do ano anterior."}
        r = Roteiro(analista=[analise()], redator=[feio, boletim()], revisor=[parecer()])
        res = self.gerar(r)
        self.assertEqual(res["versoes_do_redator"], 2)

    def test_boletim_final_sai_com_separador_de_milhar(self):
        r = Roteiro(analista=[analise()], redator=[{**boletim(), "panorama": ["Estoque de 25439."]}], revisor=[parecer()])
        res = self.gerar(r)
        self.assertEqual(res["boletim"]["panorama"], ["Estoque de 25.439."])
        self.assertEqual(res["situacao"], "aguardando_aprovacao")

    def test_evidencias_numeros_da_fonte_e_leituras(self):
        evid = {"triadas": [{"relevante": True, "titulo": "Call center abre vagas", "link": "https://ex.com/a",
                             "fonte": "g1 Sergipe", "publicado_em": "2026-09-20T12:00:00+00:00"}],
                "evidencias": [{"fato": "Anunciou 300 vagas.", "numeros": ["300"], "fonte": "g1 Sergipe",
                                "data": "2026-09-20", "janela": "recente", "apoia_hipotese": False}]}
        com_fonte = {**boletim(), "pontos_de_atencao": ["Segundo o g1, em 20 de setembro, 300 vagas foram anunciadas."]}
        r = Roteiro(analista=[analise()], redator=[com_fonte], revisor=[parecer()])
        res = self.gerar(r, evidencias=evid)
        self.assertEqual(res["situacao"], "aguardando_aprovacao")   # 300 vem da notícia, não é inventado
        md = (Path(res["pasta"]) / "boletim.md").read_text()
        self.assertIn("## Leituras relacionadas", md)
        self.assertIn("[Call center abre vagas](https://ex.com/a), g1 Sergipe, 2026-09-20", md)
        # os mesmos fatos sem evidências são outro resultado (outra pasta)
        sem = self.gerar(Roteiro(analista=[analise()], redator=[boletim()], revisor=[parecer()]))
        self.assertNotEqual(sem["pasta"], res["pasta"])

    def test_revisor_que_falha_nao_derruba_o_boletim(self):
        invalido = {"resumo": "x", "problemas": [{"tipo": "estilo", "gravidade": "altissima", "trecho": "a", "sugestao": "b"}]}
        r = Roteiro(analista=[analise()], redator=[boletim()], revisor=[invalido])
        res = self.gerar(r)
        self.assertEqual(res["situacao"], "aguardando_aprovacao")
        self.assertTrue(res["revisor_falhou"])
        self.assertIn("REVISOR AUTOMÁTICO FALHOU", res["parecer_revisor"]["resumo"])

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
        r = Roteiro(analista=[analise(["x"]), analise()], redator=[boletim("−91")], revisor=[parecer(grave=True)])
        res = self.gerar(r)
        self.assertEqual(sum(r.chamadas.values()), 7)
        self.assertEqual(res["situacao"], "reprovado_no_verificador")

    def test_modelos_do_ambiente(self):
        m = boletim_ia.modelos_do_ambiente(self.cfg)
        self.assertEqual((m["redator"], m["revisor"], m["analista"]), (REDATOR, REVISOR, REVISOR))
        # o Jev no fim da lista não vira analista nem revisor
        com_jev = ia.ConfigIA(**{**self.cfg.__dict__, "modelos_permitidos": (REDATOR, REVISOR, "typesafe/jev-1.13")})
        self.assertEqual(boletim_ia.modelos_do_ambiente(com_jev)["revisor"], REVISOR)
        vazio = ia.ConfigIA(**{**self.cfg.__dict__, "modelos_permitidos": ()})
        with self.assertRaises(RuntimeError):
            boletim_ia.modelos_do_ambiente(vazio)




JEV = "typesafe/jev-1.13"
ADVISOR = "teste/advisor"


def analise_com(*duvidas):
    return {**analise(), "duvidas": [{"pergunta": p, "tipo": tipo, "ids": ["panorama.saldo"], "por_que": "x"}
                                     for p, tipo in duvidas]}


class Ticket3b2(unittest.TestCase):
    """3b-2: triagem de dúvidas, advisor, tickets com estado salvo e julgamento de afirmações.
    Reaproveita a preparação do Fluxo sem herdar (e re-executar) os testes dele."""

    def tearDown(self):
        Fluxo.tearDown(self)

    def setUp(self):
        Fluxo.setUp(self)
        self.cfg = ia.ConfigIA(**{**self.cfg.__dict__, "modelos_permitidos": (REDATOR, REVISOR, ADVISOR, JEV)})
        listagem = {"data": [{"id": m, "pricing": {"prompt": "0.000001", "completion": "0.000004"}}
                             for m in (REDATOR, REVISOR, ADVISOR)]}
        self.precos = ia.Precos(self.pasta, baixar=lambda: listagem, baixar_endpoints=lambda m: {
            "data": {"endpoints": [{"pricing": {"prompt": "0.000000042", "completion": "0"}}]}})
        self.jev = []  # respostas do Jev, em ordem

    def post(self, chave, corpo, timeout):
        return {"answers": self.jev.pop(0), "usage": {"cost": 1e-05}}

    def gerar(self, roteiro, com_juiz=True, **kw):
        modelos = {**self.modelos, "advisor": ADVISOR, **({"juiz": JEV} if com_juiz else {})}
        return boletim_ia.gerar(FATOS, self.cfg, modelos, criar_modelo=roteiro.criar_modelo, precos=self.precos,
                                registro=self.registro, post_decisoes=self.post, **kw)

    def test_duvida_de_metodo_vai_ao_advisor_e_orienta_o_redator(self):
        r = Roteiro(analista=[analise_com(("Comparar taxa ou saldo?", "metodo"))], redator=[boletim()],
                    revisor=[parecer()], advisor=[{"resposta": "Compare taxas entre territórios.", "confianca": "alta"}])
        self.jev = [{"tipo": {"choice": "metodo", "confidence": 0.9}}]
        res = self.gerar(r)
        self.assertEqual(r.chamadas["advisor"], 1)
        self.assertIn("Compare taxas entre territórios", r.prompts["redator"][0])
        self.assertEqual(res["orientacoes_do_advisor"][0]["confianca"], "alta")

    def test_jev_descarta_duvida_que_os_fatos_respondem(self):
        r = Roteiro(analista=[analise_com(("O saldo foi negativo?", "metodo"))], redator=[boletim()],
                    revisor=[parecer()], advisor=[{"resposta": "x", "confianca": "alta"}])
        self.jev = [{"tipo": {"choice": "nenhuma", "confidence": 0.95}}]
        res = self.gerar(r)
        self.assertEqual(r.chamadas["advisor"], 0)
        self.assertEqual(res["decisoes"][0]["destino"], "nenhuma")

    def test_fato_local_abre_ticket_e_retoma_sem_pagar_o_analista_de_novo(self):
        r = Roteiro(analista=[analise_com(("Houve fechamento de obra em julho?", "fato_local"))], redator=[boletim()],
                    revisor=[parecer()], advisor=[{"resposta": "x", "confianca": "alta"}])
        self.jev = [{"tipo": {"choice": "fato_local", "confidence": 0.99}}]
        res = self.gerar(r)
        self.assertEqual(res["situacao"], "aguardando_resposta")
        self.assertEqual(r.chamadas["redator"], 0)
        # sem resposta: nem roda
        with self.assertRaises(boletim_ia.AguardandoResposta):
            self.gerar(r)
        self.assertEqual(r.chamadas["analista"], 1)
        boletim_ia.responder_ticket(self.cfg, "280480", "202607", 1, "Sim, a obra X terminou em junho.", "Fulana")
        res = self.gerar(r)
        self.assertEqual(res["situacao"], "aguardando_aprovacao")
        self.assertEqual(r.chamadas["analista"], 1)  # análise reaproveitada do ticket
        self.assertIn("a obra X terminou em junho", r.prompts["redator"][0])
        base = boletim_ia.conhecimento_local(self.cfg, "280480")
        self.assertEqual(base[0]["respondido_por"], "Fulana")

    def test_sem_tickets_segue_sem_afirmar(self):
        r = Roteiro(analista=[analise_com(("Houve fechamento de obra?", "fato_local"))], redator=[boletim()],
                    revisor=[parecer()], advisor=[{"resposta": "x", "confianca": "alta"}])
        self.jev = [{"tipo": {"choice": "fato_local", "confidence": 0.99}}]
        res = self.gerar(r, sem_tickets=True)
        self.assertEqual(res["situacao"], "aguardando_aprovacao")
        self.assertIn("SEM RESPOSTA", r.prompts["redator"][0])

    def test_afirmacao_nao_sustentada_vai_destacada(self):
        com_afirmacoes = {**boletim(), "afirmacoes": [
            {"texto": "O saldo foi negativo.", "ids": ["panorama.saldo"]},
            {"texto": "Serviços puxou a queda por causa das eleições.", "ids": ["panorama.saldo"]}]}
        r = Roteiro(analista=[analise()], redator=[com_afirmacoes], revisor=[parecer()],
                    advisor=[{"resposta": "x", "confianca": "alta"}])
        self.jev = [{"sustentada": {"noul": 0.95}}, {"sustentada": {"noul": 0.1}}]
        res = self.gerar(r)
        self.assertEqual([a["texto"] for a in res["afirmacoes_nao_sustentadas"]],
                         ["Serviços puxou a queda por causa das eleições."])

    def test_sem_juiz_funciona_como_antes(self):
        r = Roteiro(analista=[analise_com(("Comparar taxa?", "metodo"))], redator=[boletim()], revisor=[parecer()],
                    advisor=[{"resposta": "Use taxas.", "confianca": "media"}])
        res = self.gerar(r, com_juiz=False)
        self.assertEqual(res["afirmacoes_nao_sustentadas"], [])
        self.assertEqual(r.chamadas["advisor"], 1)


if __name__ == "__main__":
    unittest.main()
