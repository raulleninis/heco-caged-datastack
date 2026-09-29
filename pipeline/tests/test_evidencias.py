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


if __name__ == "__main__":
    unittest.main()
