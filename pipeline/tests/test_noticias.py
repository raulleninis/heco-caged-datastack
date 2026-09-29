"""
Testes do coletor diário de notícias (F19 parte 4). Sem rede: `baixar` é substituído.

Rodar:
    docker compose run --rm --no-deps -v ./pipeline/tests:/app/tests \\
        --entrypoint python pipeline -m unittest discover -s /app/tests -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "flows"))

import noticias  # noqa: E402

RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>X</title>
<item><title>Empresa abre 200 vagas em Socorro</title><link>https://ex.com/a</link>
<pubDate>Mon, 28 Sep 2026 10:00:00 -0300</pubDate><description>&lt;p&gt;Texto &amp;amp; resumo&lt;/p&gt;</description></item>
<item><title>Feira em Aracaju</title><link>https://ex.com/b</link><pubDate>Fri, 31 Jul 2026 23:30:00 -0300</pubDate></item>
<item><title></title><link>https://ex.com/sem-titulo</link></item>
</channel></rss>""".encode("utf-8")

ATOM = """<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Y</title>
<entry><title>Indústria em Sergipe</title><link rel="alternate" href="https://ex.org/c"/>
<published>2026-09-20T12:00:00Z</published><summary>Resumo atom</summary></entry></feed>""".encode("utf-8")

ROBOTS_LIVRE = b"User-agent: *\nDisallow: /admin\n"
FONTE = {"nome": "Fonte A", "feed": "https://ex.com/feed/", "escala": "regional", "intervalo_s": 10}


def baixador(respostas: dict):
    chamadas = []

    def baixar(url):
        chamadas.append(url)
        r = respostas[url]
        if isinstance(r, Exception):
            raise r
        return r
    baixar.chamadas = chamadas
    return baixar


class Leitura(unittest.TestCase):
    def test_rss_com_html_no_resumo_e_data_em_utc(self):
        itens = noticias.ler_feed(RSS)
        self.assertEqual([i["link"] for i in itens], ["https://ex.com/a", "https://ex.com/b"])  # sem título: fora
        self.assertEqual(itens[0]["resumo"], "Texto & resumo")
        self.assertEqual(itens[0]["publicado_em"], "2026-09-28T13:00:00+00:00")
        # 31/07 23:30 no Brasil já é agosto em UTC: o mês do arquivo segue a data em UTC
        self.assertEqual(itens[1]["publicado_em"][:7], "2026-08")

    def test_dois_documentos_colados_na_mesma_resposta(self):
        # caso real do feed do Sebrae SE (29/09/2026): dois <rss> inteiros em sequência
        itens = noticias.ler_feed(RSS + b"\n" + ATOM)
        self.assertEqual(len(itens), 3)

    def test_xml_quebrado_sem_nenhum_item_e_erro(self):
        with self.assertRaises(Exception):
            noticias.ler_feed(b"<rss><channel><item>")

    def test_atom(self):
        itens = noticias.ler_feed(ATOM)
        self.assertEqual((itens[0]["link"], itens[0]["publicado_em"]), ("https://ex.org/c", "2026-09-20T12:00:00+00:00"))

    def test_fonte_com_escala_invalida_e_erro(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "f.toml")
            p.write_text('[[fontes]]\nnome="x"\nfeed="https://x"\nescala="global"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                noticias.carregar_fontes(p)

    def test_fontes_da_instancia_sao_validas(self):
        self.assertTrue(noticias.carregar_fontes())


class Coleta(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self.tmp.name)
        self.esperas = []

    def tearDown(self):
        self.tmp.cleanup()

    def coletar(self, fontes, respostas, avisar=None):
        return noticias.coletar(fontes, noticias.Arquivo(self.pasta), baixador(respostas),
                                dormir=self.esperas.append, avisar=avisar)

    def test_grava_por_mes_e_nao_duplica(self):
        resp = {"https://ex.com/robots.txt": ROBOTS_LIVRE, FONTE["feed"]: RSS}
        self.assertEqual(self.coletar([FONTE], resp), {"Fonte A": 2})
        self.assertEqual(self.coletar([FONTE], resp), {"Fonte A": 0})
        setembro = noticias.Arquivo(self.pasta).ler("2026-09")
        self.assertEqual([n["titulo"] for n in setembro], ["Empresa abre 200 vagas em Socorro"])
        self.assertEqual((setembro[0]["fonte"], setembro[0]["escala"]), ("Fonte A", "regional"))
        self.assertEqual(len(noticias.Arquivo(self.pasta).ler("2026-08")), 1)

    def test_agregador_separa_veiculo_e_titulo_repetido_nao_entra(self):
        gn = {"nome": "GN", "feed": "https://news.example/rss", "escala": "estadual", "agregador": True}
        rss_gn = RSS.replace(b"Empresa abre 200 vagas em Socorro</title><link>https://ex.com/a",
                             b"Empresa abre 200 vagas em Socorro - Infonet</title><link>https://news.example/x")
        resp = {"https://ex.com/robots.txt": ROBOTS_LIVRE, FONTE["feed"]: RSS,
                "https://news.example/robots.txt": ROBOTS_LIVRE, gn["feed"]: rss_gn}
        r = self.coletar([FONTE, gn], resp)
        # as duas notícias do GN já vieram pela Fonte A: a de Socorro com OUTRO link (barrada
        # pelo título, depois de separar " - Infonet") e a da feira com o mesmo link
        self.assertEqual(r, {"Fonte A": 2, "GN": 0})
        self.assertEqual(noticias.separar_veiculo({"titulo": "Pix cresce em Sergipe - Jornal X", "link": "l"}),
                         {"titulo": "Pix cresce em Sergipe", "veiculo": "Jornal X", "link": "l"})

    def test_fonte_com_erro_nao_derruba_as_outras(self):
        outra = {**FONTE, "nome": "Fonte B", "feed": "https://ex.org/feed/"}
        resp = {"https://ex.com/robots.txt": ROBOTS_LIVRE, FONTE["feed"]: OSError("fora do ar"),
                "https://ex.org/robots.txt": ROBOTS_LIVRE, outra["feed"]: ATOM}
        r = self.coletar([FONTE, outra], resp)
        self.assertTrue(r["Fonte A"].startswith("erro: OSError"))
        self.assertEqual(r["Fonte B"], 1)

    def test_robots_que_proibe_nao_baixa_o_feed(self):
        resp = {"https://ex.com/robots.txt": b"User-agent: *\nDisallow: /\n", FONTE["feed"]: RSS}
        b = baixador(resp)
        r = noticias.coletar([FONTE], noticias.Arquivo(self.pasta), b, dormir=self.esperas.append)
        self.assertIn("robots.txt", r["Fonte A"])
        self.assertNotIn(FONTE["feed"], b.chamadas)

    def test_intervalo_entre_requisicoes_ao_mesmo_host(self):
        segunda = {**FONTE, "nome": "Fonte A2", "feed": "https://ex.com/outra/feed/"}
        resp = {"https://ex.com/robots.txt": ROBOTS_LIVRE, FONTE["feed"]: RSS, segunda["feed"]: ATOM}
        self.coletar([FONTE, segunda], resp)
        self.assertEqual(len(self.esperas), 1)
        self.assertGreater(self.esperas[0], 9)

    def test_alerta_so_no_terceiro_dia_seguido_de_falha(self):
        avisos = []
        resp = {"https://ex.com/robots.txt": ROBOTS_LIVRE, FONTE["feed"]: OSError("fora")}
        for _ in range(4):
            self.coletar([FONTE], resp, avisar=lambda n, e: avisos.append(n))
        self.assertEqual(avisos, ["Fonte A"])
        estado = json.loads((self.pasta / "estado.json").read_text())
        self.assertEqual(estado["Fonte A"]["falhas_seguidas"], 4)
        self.coletar([FONTE], {"https://ex.com/robots.txt": ROBOTS_LIVRE, FONTE["feed"]: RSS})
        estado = json.loads((self.pasta / "estado.json").read_text())
        self.assertEqual(estado["Fonte A"]["falhas_seguidas"], 0)


if __name__ == "__main__":
    unittest.main()
