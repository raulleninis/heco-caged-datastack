"""
Testes das evidências externas (F19 parte 4): janelas, seleção por código e triagem pelo Jev
(com a resposta do Jev simulada; sem rede).

Rodar:
    docker compose run --rm --no-deps -v ./pipeline/tests:/app/tests \\
        --entrypoint python pipeline -m unittest discover -s /app/tests -v
"""

import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "flows"))

import evidencias as ev  # noqa: E402
import ia  # noqa: E402

JS = ev.janelas(202607, date(2026, 9, 29))
TERMOS = ["nossa senhora do socorro", "aracaju", "sergipe"]


def noticia(titulo, data, fonte="g1 Sergipe", escala="estadual", link=None, resumo=""):
    return {"titulo": titulo, "resumo": resumo, "publicado_em": f"{data}T12:00:00+00:00", "fonte": fonte,
            "escala": escala, "link": link or f"https://ex.com/{abs(hash(titulo))}"}


class Janelas(unittest.TestCase):
    def test_competencia_vai_do_mes_anterior_a_15_dias_depois(self):
        self.assertEqual(JS["competencia"], (date(2026, 6, 1), date(2026, 8, 15)))
        self.assertEqual(JS["recente"], (date(2026, 8, 30), date(2026, 9, 29)))
        self.assertEqual(ev.janelas(202601, date(2026, 3, 1))["competencia"][0], date(2025, 12, 1))

    def test_noticia_classificada_pela_data(self):
        self.assertEqual(ev.janela_da("2026-07-10T00:00:00+00:00", JS), "competencia")
        self.assertEqual(ev.janela_da("2026-09-20T00:00:00+00:00", JS), "recente")
        self.assertIsNone(ev.janela_da("2026-08-20T00:00:00+00:00", JS))  # entre as janelas

    def test_meses_entre(self):
        self.assertEqual(ev.meses_entre(date(2025, 11, 5), date(2026, 2, 1)), ["2025-11", "2025-12", "2026-01", "2026-02"])


class Selecao(unittest.TestCase):
    def selecionar(self, noticias, exclusoes=None):
        return ev.selecionar(noticias, JS, TERMOS, ["Serviços"], exclusoes or {})

    def test_territorio_e_tema(self):
        s = self.selecionar([
            noticia("Call center em Aracaju abre 300 vagas", "2026-07-10"),
            noticia("Debate entre candidatos em Sergipe", "2026-07-11"),          # sem tema
            noticia("Comércio de Manaus contrata para o Natal", "2026-07-12"),    # sem território
        ])
        self.assertEqual([x["titulo"] for x in s], ["Call center em Aracaju abre 300 vagas"])
        self.assertEqual((s[0]["janela"], s[0]["setores"]), ("competencia", ["Serviços"]))

    def test_nacional_passa_sem_territorio_so_com_setor_em_destaque_ou_emprego(self):
        s = self.selecionar([
            noticia("Bancos anunciam novas regras de crédito", "2026-09-20", "g1 Economia", "nacional"),
            noticia("Safra de milho bate recorde", "2026-09-21", "g1 Economia", "nacional"),
        ])
        self.assertEqual([x["titulo"] for x in s], ["Bancos anunciam novas regras de crédito"])

    def test_exclusao_por_link(self):
        fonte = "Agência Sebrae SE: economia e política"
        s = self.selecionar([
            noticia("Sebrae apoia comércio em Sergipe", "2026-09-20", fonte, link="https://se.agenciasebrae.com.br/a"),
            noticia("Sebrae apoia comércio em Sergipe e Santa Catarina", "2026-09-20", fonte,
                    link="https://sc.agenciasebrae.com.br/b"),
        ], {fonte: r"^https?://(?!se\.)[a-z]{2}\.agenciasebrae\.com\.br"})
        self.assertEqual([x["link"] for x in s], ["https://se.agenciasebrae.com.br/a"])

    def test_conteudo_patrocinado_fica_de_fora(self):
        s = self.selecionar([noticia("Empresa de Aracaju amplia serviço e contrata", "2026-09-28",
                                     link="https://g1.globo.com/se/sergipe/especial-publicitario/x/noticia/a.ghtml")])
        self.assertEqual(s, [])

    def test_prioridade_ordena_dentro_da_janela(self):
        s = self.selecionar([
            noticia("Comércio de Aracaju vende mais", "2026-09-25"),
            noticia("Call center em Aracaju demite 200", "2026-09-10"),
        ])
        self.assertEqual(s[0]["titulo"], "Call center em Aracaju demite 200")  # setor em destaque + emprego


class Triagem(unittest.TestCase):
    def test_relevancia_pelo_jev(self):
        with tempfile.TemporaryDirectory() as d:
            pasta = Path(d)
            cfg = ia.ConfigIA(api_key="sk", modelos_permitidos=("typesafe/jev-1.13",), orcamento_mensal_usd=Decimal("2"),
                              preco_max_saida_usd_mtok=Decimal("15"), pasta=pasta)
            precos = ia.Precos(pasta, baixar=lambda: {"data": []}, baixar_endpoints=lambda m: {
                "data": {"endpoints": [{"pricing": {"prompt": "0.000000042", "completion": "0"}}]}})
            respostas = iter([
                {"territorio": {"choice": "municipio_ou_regiao"}, "emprego": {"noul": 0.9}},
                {"territorio": {"choice": "outro"}, "emprego": {"noul": 0.95}},
                {"territorio": {"choice": "estado"}, "emprego": {"noul": 0.2}},
            ])
            fatos = {"territorio": {"nome": "Socorro"}, "setorial": {"destaques": ["Serviços"]},
                     "comparacao": {"regioes": [{"nome": "RMA"}], "uf": {"nome": "Sergipe"}}}
            candidatas = [noticia("a", "2026-09-20"), noticia("b", "2026-09-20"), noticia("c", "2026-09-20")]
            with ia.Execucao(cfg, {"juiz": "typesafe/jev-1.13"}, precos=precos, registro=ia.RegistroCustos(pasta)) as ex:
                ex.post_decisoes = lambda k, corpo, t: {"answers": next(respostas), "usage": {"cost": 1e-05}}
                triadas = ev.triar(ex, candidatas, fatos)
            self.assertEqual([t["relevante"] for t in triadas], [True, False, False])


HTML = """<html><head><script>var x = "<p>não é texto</p>";</script></head><body>
<p>Curto.</p><p>A empresa de teleatendimento anunciou 300 novas vagas em Aracaju para outubro.</p>
<p>As contratações começam na próxima semana, segundo a direção da unidade local.</p></body></html>""".encode()
ROBOTS = b"User-agent: *\nDisallow: /admin\n"


class Leitura(unittest.TestCase):
    def test_paragrafos_sem_script_e_sem_linhas_curtas(self):
        n = {"link": "https://ex.com/a", "resumo": "resumo"}
        texto = ev.texto_da_noticia(n, baixar=lambda u: ROBOTS if u.endswith("robots.txt") else HTML, dormir=lambda s: None)
        self.assertTrue(texto.startswith("A empresa de teleatendimento anunciou 300 novas vagas"))
        self.assertNotIn("não é texto", texto)
        self.assertNotIn("Curto.", texto)

    def test_robots_que_proibe_fica_so_o_resumo(self):
        n = {"link": "https://ex.com/a", "resumo": "resumo do feed"}
        texto = ev.texto_da_noticia(n, baixar=lambda u: b"User-agent: *\nDisallow: /\n" if u.endswith("robots.txt") else HTML,
                                    dormir=lambda s: None)
        self.assertEqual(texto, "resumo do feed")


class Pesquisa(unittest.TestCase):
    def setUp(self):
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.usage import RequestUsage
        self.tmp = tempfile.TemporaryDirectory()
        pasta = Path(self.tmp.name)
        self.cfg = ia.ConfigIA(api_key="sk", modelos_permitidos=("typesafe/jev-1.13", "teste/texto"),
                               orcamento_mensal_usd=Decimal("2"), preco_max_saida_usd_mtok=Decimal("15"), pasta=pasta)
        self.precos = ia.Precos(pasta, baixar=lambda: {"data": [{"id": "teste/texto", "pricing": {"prompt": "0.000001", "completion": "0.000004"}}]},
                                baixar_endpoints=lambda m: {"data": {"endpoints": [{"pricing": {"prompt": "0.000000042", "completion": "0"}}]}})
        self.registro = ia.RegistroCustos(pasta)
        self.saidas = []

        def fn(msgs, info):
            saida = self.saidas.pop(0) if len(self.saidas) > 1 else self.saidas[0]
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, saida)],
                                 usage=RequestUsage(input_tokens=2000, output_tokens=300), provider_details={"cost": 0.0005})
        self.agente = ev.criar_pesquisador(FunctionModel(fn, model_name="teste/texto"))
        self.fatos = {"rotulos": {"competencia": "julho de 2026"}, "setorial": {"grupamentos": {
            "Serviços": {"saldo": {"valor": -90}, "sazonalidade": {"posicao": "abaixo_da_faixa"}}}}}

    def tearDown(self):
        self.tmp.cleanup()

    def rodar(self, relevantes, jev=0.9):
        with ia.Execucao(self.cfg, {"juiz": "typesafe/jev-1.13", "pesquisador": "teste/texto"},
                         precos=self.precos, registro=self.registro) as ex:
            ex.post_decisoes = lambda k, c, t: {"answers": {"compativel": {"noul": jev}}, "usage": {"cost": 1e-05}}
            baixar = lambda u: ROBOTS if u.endswith("robots.txt") else HTML
            return ev.pesquisar(ex, self.agente, relevantes, self.fatos, baixar=baixar, dormir=lambda s: None)

    def relevante(self, id_, janela):
        return {**noticia(f"Notícia {id_}", "2026-07-10" if janela == "competencia" else "2026-09-20"),
                "id": id_, "janela": janela, "prioridade": 3, "link": f"https://ex.com/{id_}"}

    def test_numero_fora_do_texto_gera_nova_tentativa(self):
        errada = {"evidencias": [{"id": "a", "fato": "Anunciou 500 vagas.", "numeros": ["500"], "territorio": "Aracaju", "setor": "Serviços"}]}
        certa = {"evidencias": [{"id": "a", "fato": "Anunciou 300 vagas.", "numeros": ["300"], "territorio": "Aracaju", "setor": "Serviços"}]}
        self.saidas = [errada, certa]
        evid = self.rodar([self.relevante("a", "recente")])
        self.assertEqual(evid[0]["fato"], "Anunciou 300 vagas.")
        self.assertFalse(evid[0]["apoia_hipotese"])       # recente nunca apoia hipótese
        self.assertNotIn("prob_compativel", evid[0])       # e nem é julgada

    def test_hipotese_so_na_janela_da_competencia_e_acima_do_limiar(self):
        self.saidas = [{"evidencias": [
            {"id": "a", "fato": "Anunciou 300 vagas.", "numeros": ["300"], "territorio": "Aracaju", "setor": "Serviços"}]}]
        self.assertTrue(self.rodar([self.relevante("a", "competencia")], jev=0.9)[0]["apoia_hipotese"])
        self.assertFalse(self.rodar([self.relevante("a", "competencia")], jev=0.5)[0]["apoia_hipotese"])


if __name__ == "__main__":
    unittest.main()
