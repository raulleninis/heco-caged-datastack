"""
Testes da projeção da seção Perspectivas (F21): identidade contábil, faixa, validações que
bloqueiam, textos fixos, edições publicadas e revisão. Dados sintéticos, sem rede.

O teste de aceitação da especificação (seção 11) roda quando PROJECAO_ACEITACAO_DB aponta para um
warehouse com dados até 2026-07 (ex.: data/warehouse/caged.duckdb.bak-20260929):
    docker compose run --rm --no-deps -v ./pipeline/tests:/app/tests \\
        -e PROJECAO_ACEITACAO_DB=/data/warehouse/caged.duckdb.bak-20260929 \\
        --entrypoint python pipeline -m unittest tests.test_projecao -v
"""

import math
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "flows"))

import projecao as pj  # noqa: E402

# Backtest mais curto que o de produção: os testes conferem a mecânica, não os números.
CFG = pj.Config(backtest_primeira_origem="2025-01")


def criar_warehouse(caminho: Path, ate: str = "202608", pular: str | None = None) -> Path:
    """mart_caged_reconciliado sintético, de 202001 até `ate`: sazonal, com ruído fixo."""
    rnd = random.Random(42)
    con = duckdb.connect(str(caminho))
    con.execute("create table mart_caged_reconciliado (competencia_mov bigint, grupamento varchar, "
                "admissoes_consolidadas bigint, desligamentos_consolidados bigint)")
    ano, mes = 2020, 1
    while f"{ano}{mes:02d}" <= ate:
        comp = f"{ano}{mes:02d}"
        if comp != pular:
            base = 1000 + 150 * math.sin(2 * math.pi * mes / 12)
            a = int(base + rnd.randint(-60, 60) + 5 * (ano - 2020))
            d = int(base - 10 + rnd.randint(-60, 60) + 5 * (ano - 2020))
            # dois grupamentos: o fluxo do município é a soma
            con.execute("insert into mart_caged_reconciliado values (?, 'A', ?, ?), (?, 'B', ?, ?)",
                        [int(comp), a // 2, d // 2, int(comp), a - a // 2, d - d // 2])
        mes += 1
        if mes == 13:
            ano, mes = ano + 1, 1
    con.close()
    return caminho


class ProjecaoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self.tmp.name)
        self.wh = criar_warehouse(self.pasta / "w.duckdb")

    def tearDown(self):
        self.tmp.cleanup()

    def gerar(self, **kw):
        return pj.gerar_projecao(self.wh, 25000, territorio="280480", cfg=CFG, pasta=self.pasta / "ed", **kw)

    def test_identidade_faixa_e_indicadores(self):
        r = self.gerar()
        self.assertEqual((r["edicao"], r["ano"], r["ano_prox"]), ("2026-08", 2026, 2027))
        mensal = r["projecao_mensal"]
        self.assertEqual(len(mensal), 16)                      # set/2026 a dez/2027
        anterior = r["estoque_ancora"]
        for p in mensal:                                       # saldo e estoque saem dos fluxos
            self.assertAlmostEqual(p["estoque"] - anterior, p["saldo"], delta=0.02)
            self.assertLessEqual(p["estoque_lo"], p["estoque"])
            self.assertGreaterEqual(p["estoque_hi"], p["estoque"])
            anterior = p["estoque"]
        larguras = [p["estoque_hi"] - p["estoque_lo"] for p in mensal]
        self.assertGreater(larguras[-1], 0)
        k = r["kpis"]
        dez = next(p for p in mensal if p["competencia"] == "2026-12")
        self.assertAlmostEqual(k["estoque_dez_ano"], dez["estoque"], delta=0.01)
        self.assertAlmostEqual(k["estoque_dez_prox"], mensal[-1]["estoque"], delta=0.01)
        self.assertEqual(r["historico"][0]["competencia"], "2025-01")   # gráfico: jan do ano anterior
        self.assertEqual(r["historico"][-1]["estoque"], 25000)

    def test_edicao_de_dezembro_projeta_ate_dezembro_do_ano_seguinte_ao_de_referencia(self):
        criar_warehouse(self.wh.with_name("dez.duckdb"), ate="202612")
        r = pj.gerar_projecao(self.wh.with_name("dez.duckdb"), 25000, cfg=CFG)
        self.assertEqual((r["ano"], r["ano_prox"]), (2027, 2028))
        self.assertEqual(len(r["projecao_mensal"]), 24)

    def test_mes_faltando_bloqueia(self):
        criar_warehouse(self.wh.with_name("buraco.duckdb"), pular="202403")
        with self.assertRaises(pj.ProjecaoBloqueada):
            pj.gerar_projecao(self.wh.with_name("buraco.duckdb"), 25000, cfg=CFG)

    def test_revisao_recalculada_e_depois_armazenada(self):
        r = self.gerar()
        self.assertEqual(r["revisao"]["origem"], "recalculada")
        self.assertTrue(any("recalculada" in a for a in r["avisos"]))
        pj.salvar_edicao("280480", r, pasta=self.pasta / "ed")
        pj.salvar_edicao("280480", r, pasta=self.pasta / "ed")   # publicar de novo substitui, não duplica
        # mês seguinte publicado no CAGED (mesma semente: os meses anteriores são os mesmos)
        self.wh = criar_warehouse(self.pasta / "w2.duckdb", ate="202609")
        r2 = self.gerar()
        self.assertEqual(r2["edicao"], "2026-09")
        self.assertEqual(r2["revisao"]["origem"], "armazenada")
        set26 = next(p["estoque"] for p in r["projecao_mensal"] if p["competencia"] == "2026-09")
        self.assertAlmostEqual(r2["revisao"]["proj_anterior_mes_atual"], set26, delta=0.01)
        self.assertIn("Na edição anterior, a projeção para o estoque de setembro", r2["texto"]["revisao"])
        con = duckdb.connect(str(pj.arquivo_edicoes("280480", self.pasta / "ed")), read_only=True)
        self.assertEqual(con.execute("select count(*) from projecao_edicoes").fetchone()[0], 16)
        con.close()

    def test_leitura_do_saldo_do_ano(self):
        r = self.gerar()
        for faixa, leitura in (([10, 50], "crescimento"), ([-50, -10], "retração"), ([-10, 50], "estabilidade")):
            r["kpis"]["saldo_ano_faixa"] = faixa
            self.assertIn(f"o que indica {leitura}", pj.redigir_texto(r)["paragrafo"])

    def test_textos_fixos_e_sinal_de_menos(self):
        t = self.gerar()["texto"]
        self.assertTrue(t["paragrafo"].startswith("Com base no padrão histórico de admissões e desligamentos"))
        self.assertTrue(t["legenda"].startswith("Estoque de vínculos formais, jan/25 a dez/27."))
        self.assertIn("8 de cada 10 testes", t["legenda"])
        self.assertIn("ajustes e refinamentos na metodologia", t["aviso_experimental"])
        self.assertIn("Fragilidades conhecidas", t["fragilidades"])
        self.assertEqual(pj._sg(-248), "−248")                 # sinal de menos U+2212
        self.assertEqual(pj._sg(1042), "+1.042")

    def test_anexar_sem_ancora_tira_a_secao_e_mantem_o_boletim(self):
        fatos = {"territorio": {"codigo": "280480"}, "competencia": "202608", "panorama": {}, "numeros": {}}
        f = pj.anexar(fatos, self.wh, pasta=self.pasta / "ed")
        self.assertNotIn("projecao", f)
        self.assertIn("âncora", f["projecao_ausente"])
        self.assertIn("hash", f)

    def test_anexar_recusa_serie_de_outra_competencia(self):
        fatos = {"territorio": {"codigo": "280480"}, "competencia": "202607",
                 "panorama": {"estoque": {"valor": 25000}}, "numeros": {}}
        f = pj.anexar(fatos, self.wh, pasta=self.pasta / "ed")
        self.assertIn("competência do boletim", f["projecao_ausente"])


@unittest.skipUnless(os.environ.get("PROJECAO_ACEITACAO_DB"), "defina PROJECAO_ACEITACAO_DB para o teste de aceitação")
class AceitacaoTest(unittest.TestCase):
    """Seção 11 da especificação: dados até 2026-07 + agosto do boletim, âncora 25.364, sem edições."""

    def test_valores_esperados(self):
        with tempfile.TemporaryDirectory() as vazio:
            r = pj.gerar_projecao(os.environ["PROJECAO_ACEITACAO_DB"], 25364, complemento={"2026-08": (1028, 1107)},
                                  pasta=Path(vazio))
        k, bt, rv = r["kpis"], r["backtest"], r["revisao"]
        perto = lambda a, b: self.assertLessEqual(abs(round(a) - b), 2, (a, b))  # noqa: E731
        self.assertEqual(bt["n_origens"], 44)
        for valor, esperado in ((k["estoque_dez_ano"], 25673), (k["estoque_dez_ano_faixa"][0], 25162),
                                (k["estoque_dez_ano_faixa"][1], 26315), (k["saldo_ano"], 42),
                                (k["saldo_ano_faixa"][0], -469), (k["saldo_ano_faixa"][1], 684),
                                (k["estoque_dez_prox"], 25780), (k["estoque_dez_prox_faixa"][0], 24485),
                                (k["estoque_dez_prox_faixa"][1], 26640),
                                (rv["proj_anterior_mes_atual"], 25612), (rv["proj_anterior_dez_ano"], 26075),
                                (bt["mae"]["comb"]["S12"], 591), (bt["mae"]["ingenuo"]["S12"], 623)):
            perto(valor, esperado)
        set26 = r["projecao_mensal"][0]
        for valor, esperado in ((set26["admissoes"], 1012), (set26["desligamentos"], 909), (set26["saldo"], 103)):
            perto(valor, esperado)
        self.assertEqual(rv["origem"], "recalculada")


if __name__ == "__main__":
    unittest.main()
