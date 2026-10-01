"""
Testes dos indicadores externos (F19 parte 4): Pix por município e Selic do Banco Central, com
as respostas das APIs simuladas (sem rede).

Rodar:
    docker compose run --rm --no-deps -v ./pipeline/tests:/app/tests \\
        --entrypoint python pipeline -m unittest discover -s /app/tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "flows"))

import fatos as fatos_mod  # noqa: E402
import indicadores as ind  # noqa: E402

# Socorro 2804805, Aracaju 2800308 (região), Estância 2802106 (fora da região)
PIX = {
    202607: [(2804805, 5184, 789.1e6), (2800308, 30000, 5000e6), (2802106, 1000, 100e6)],
    202507: [(2804805, 4258, 639.6e6), (2800308, 25000, 4500e6), (2802106, 900, 90e6)],
}
FATOS = {"competencia": "202607", "territorio": {"codigo": "280480", "nome": "Socorro"},
         "comparacao": {"uf": {"nome": "Sergipe"}}, "setorial": {"destaques": ["Serviços"]},
         "numeros": {"panorama.saldo": {"valor": -83, "unidade": "vinculos", "descricao": ""}}}


def baixar_falso(url):
    if "Pix" in url:
        mes = int(url.split("AnoMes%20eq%20")[1][:6])
        return {"value": [{"AnoMes": mes, "Municipio_Ibge": c, "Municipio": "x", "QT_PES_RecebedorPJ": q,
                           "VL_RecebedorPJ": v} for c, q, v in PIX.get(mes, [])]}
    return [{"data": "01/07/2025", "valor": "15.00"}, {"data": "31/07/2026", "valor": "14.25"}]


class Indicadores(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_digito_verificador_do_ibge(self):
        self.assertEqual(ind.codigo_ibge("280480"), 2804805)
        self.assertEqual(ind.codigo_ibge("280030"), 2800308)

    def test_pix_por_territorio_regiao_e_uf_com_leitura_relativa(self):
        n = fatos_mod.Numeros()
        b = ind.bloco_pix(n, FATOS, {"RMA": ["280480", "280030"]}, baixar_falso, self.pasta)
        nomes = [r["nome"] for r in b["recortes"]]
        self.assertEqual(nomes, ["Socorro", "RMA", "Sergipe"])
        socorro, rma, uf = b["recortes"]
        self.assertEqual(socorro["empresas_recebedoras"]["valor"], 5184)
        self.assertEqual(socorro["variacao_empresas_12m"]["valor"], 21.75)       # 5184 / 4258
        self.assertEqual(rma["empresas_recebedoras"]["valor"], 35184)
        self.assertEqual(uf["empresas_recebedoras"]["valor"], 36184)            # todos os municípios
        self.assertEqual(socorro["valor_recebido_milhoes"]["valor"], 789.1)
        self.assertEqual(b["diferenca_empresas_vs_uf_pp"]["valor"],
                         round(21.75 - uf["variacao_empresas_12m"]["valor"], 2))
        self.assertTrue((self.pasta / "pix_28_202607.json").exists())          # cache em disco

    def test_meses_posteriores_ao_caged_ate_o_primeiro_que_falta(self):
        """O CAGED olha para trás; o Pix de agosto (já publicado) entra como sinal posterior a julho.
        Setembro ainda não saiu: a lista para ali."""
        PIX[202608] = [(2804805, 5300, 900e6), (2800308, 31000, 5200e6), (2802106, 1000, 100e6)]
        PIX[202508] = [(2804805, 4300, 700e6), (2800308, 26000, 4600e6), (2802106, 950, 95e6)]
        self.addCleanup(lambda: [PIX.pop(202608), PIX.pop(202508)])
        n = fatos_mod.Numeros()
        b = ind.bloco_pix(n, FATOS, {"RMA": ["280480", "280030"]}, baixar_falso, self.pasta)
        self.assertEqual([m["competencia"] for m in b["posteriores"]], ["agosto de 2026"])
        socorro = b["posteriores"][0]["recortes"][0]
        self.assertEqual(socorro["variacao_valor_12m"]["valor"], round((900 - 700) / 700 * 100, 2))
        self.assertIn("pix.posterior.202608.territorio.variacao_valor_12m", n.tabela)
        self.assertIn("não previsão", b["cuidados"])

    def test_trajetoria_inclui_meses_anteriores_publicados(self):
        """Junho entra na trajetória; maio não foi publicado e só é pulado (não interrompe)."""
        PIX[202606] = [(2804805, 5100, 700e6), (2800308, 29000, 4800e6), (2802106, 1000, 100e6)]
        PIX[202506] = [(2804805, 4200, 600e6), (2800308, 24000, 4400e6), (2802106, 900, 90e6)]
        self.addCleanup(lambda: [PIX.pop(202606), PIX.pop(202506)])
        n = fatos_mod.Numeros()
        b = ind.bloco_pix(n, FATOS, {"RMA": ["280480", "280030"]}, baixar_falso, self.pasta)
        self.assertEqual([m["competencia"] for m in b["anteriores"]], ["junho de 2026"])
        self.assertIn("pix.anterior.202606.territorio.variacao_valor_12m", n.tabela)

    def test_mes_nao_publicado_fica_sem_pix(self):
        fatos = {**FATOS, "competencia": "202612"}
        self.assertIsNone(ind.bloco_pix(fatos_mod.Numeros(), fatos, {}, baixar_falso, self.pasta))

    def test_selic_so_com_setor_sensivel_a_credito(self):
        self.assertIsNone(ind.bloco_selic(fatos_mod.Numeros(), FATOS, baixar_falso))
        com_construcao = {**FATOS, "setorial": {"destaques": ["Construção"]}}
        s = ind.bloco_selic(fatos_mod.Numeros(), com_construcao, baixar_falso)
        self.assertEqual((s["fim_do_mes"]["valor"], s["doze_meses_antes"]["valor"]), (14.25, 15.0))

    def criar_warehouse(self) -> Path:
        wh = self.pasta / "w.duckdb"
        con = duckdb.connect(str(wh))
        con.execute("create table regioes (regiao varchar, nome varchar, territorio varchar)")
        con.execute("insert into regioes values ('RMA','RMA','280480'),('RMA','RMA','280030')")
        con.close()
        return wh

    def test_anexar_registra_numeros_e_recalcula_o_hash(self):
        fatos = {**FATOS, "hash": "velho"}
        f = ind.anexar(fatos, self.criar_warehouse(), baixar_falso, self.pasta)
        self.assertIn("pix.territorio.empresas_recebedoras", f["numeros"])
        self.assertIn("panorama.saldo", f["numeros"])
        self.assertEqual(f["hash"], fatos_mod.hash_dos_fatos(f))
        self.assertNotEqual(f["hash"], "velho")

    def test_falha_de_rede_nao_derruba(self):
        def falha(url):
            raise OSError("sem rede")
        f = ind.anexar(dict(FATOS), self.criar_warehouse(), falha, self.pasta)
        self.assertEqual(f["indicadores_externos"], {})
        self.assertIn("pix", f["indicadores_ausentes"])


if __name__ == "__main__":
    unittest.main()
