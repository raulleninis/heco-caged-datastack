"""
Testes do boletim (F15/F12): leitura do mart reconciliado com a marcação provisório x
consolidado, fallback para o mart só-MOV e geração dos arquivos.

Rodar (a imagem do pipeline já tem as dependências):
    docker compose run --rm --no-deps -v ./pipeline/tests:/app/tests \\
        --entrypoint python pipeline -m unittest discover -s /app/tests -v
"""

import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "flows"))

import boletim  # noqa: E402

COMPETENCIAS = ("202506", "202605", "202606", "202607")


def criar_warehouse(caminho: Path, com_reconciliado: bool) -> None:
    con = duckdb.connect(str(caminho))
    con.execute(
        "create table mart_caged_mensal_grupamento (competencia_mov bigint, grupamento varchar, "
        "admissoes bigint, desligamentos bigint, saldo_liquido hugeint, admissoes_com_salario_valido bigint, "
        "salario_mediano_admissao double, salario_medio_admissao double, palma_index_admissao double)"
    )
    for c in COMPETENCIAS:
        for g in ("Comércio", "Serviços"):
            con.execute("insert into mart_caged_mensal_grupamento values (?,?,?,?,?,?,?,?,?)",
                        [int(c), g, 200, 190, 10, 195, 1650.0, 1800.0, 2.1])
    if com_reconciliado:
        con.execute(
            "create table mart_caged_reconciliado (competencia_mov bigint, grupamento varchar, "
            "admissoes_mov bigint, desligamentos_mov bigint, saldo_mov bigint, "
            "admissoes_fora_prazo bigint, desligamentos_fora_prazo bigint, saldo_fora_prazo bigint, "
            "admissoes_excluidas bigint, desligamentos_excluidos bigint, saldo_exclusoes bigint, "
            "admissoes_consolidadas bigint, desligamentos_consolidados bigint, saldo_consolidado bigint, "
            "ultima_competencia_carregada bigint, defasagem_meses bigint, situacao varchar)"
        )
        for c in COMPETENCIAS:
            defas = (2026 * 12 + 7) - (int(c[:4]) * 12 + int(c[4:]))
            sit = "provisório" if defas < 12 else "consolidado"
            for g in ("Comércio", "Serviços"):
                # +5 admissões fora do prazo, 1 desligamento excluído (efeito +1 no saldo)
                con.execute("insert into mart_caged_reconciliado values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            [int(c), g, 200, 190, 10, 5, 0, 5, 0, 1, 1, 205, 189, 16, 202607, defas, sit])
        # um grupamento que só existe no reconciliado (só FOR naquele mês)
        con.execute("insert into mart_caged_reconciliado values (202607,'Agropecuária',0,0,0,2,0,2,0,0,0,2,0,2,202607,0,'provisório')")
    con.close()


class BoletimTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_sem_mart_reconciliado_cai_no_so_mov_e_diz_isso(self):
        wh = self.tmp / "a.duckdb"
        criar_warehouse(wh, com_reconciliado=False)
        b = boletim.carregar(wh, "202607")
        self.assertFalse(b.reconciliado)
        self.assertIsNone(b.situacao)
        self.assertEqual(b.total["saldo_liquido"], 20)
        self.assertIn("não foram incorporadas", " ".join(boletim._notas(b)))
        pdf, xlsx = boletim.gerar(wh, "202607", self.tmp / "s")
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))

    def test_reconciliado_usa_o_saldo_consolidado_e_marca_a_situacao(self):
        wh = self.tmp / "b.duckdb"
        criar_warehouse(wh, com_reconciliado=True)
        b = boletim.carregar(wh, "202607")
        self.assertTrue(b.reconciliado)
        self.assertEqual(b.situacao, "provisório")
        self.assertEqual(b.ultima_competencia, "202607")
        # 2 grupamentos com saldo consolidado 16 + o que só tem FOR (2) = 34; só-MOV = 20
        self.assertEqual(b.total["saldo_liquido"], 34)
        self.assertEqual(b.total_so_mov, 20)
        resumo = " ".join(boletim._resumo(b))
        self.assertIn("PROVISÓRIO", resumo)
        self.assertIn("Saldo declarado dentro do prazo", resumo)
        self.assertIn("+20", resumo)
        self.assertIn("+34", resumo)

    def test_competencia_antiga_e_consolidada(self):
        wh = self.tmp / "c.duckdb"
        criar_warehouse(wh, com_reconciliado=True)
        b = boletim.carregar(wh, "202506")
        self.assertEqual(b.situacao, "consolidado")
        self.assertIn("Só exclusões tardias", " ".join(boletim._resumo(b)))
        self.assertEqual([s["situacao"] for s in b.serie], ["consolidado"])  # só existe 202506 até ali

    def test_grupamento_so_com_fora_do_prazo_aparece_sem_salario(self):
        wh = self.tmp / "d.duckdb"
        criar_warehouse(wh, com_reconciliado=True)
        b = boletim.carregar(wh, "202607")
        agro = next(l for l in b.linhas if l["grupamento"] == "Agropecuária")
        self.assertEqual((agro["admissoes"], agro["saldo_liquido"]), (2, 2))
        self.assertIsNone(agro["salario_mediano_admissao"])

    def test_serie_marca_provisorio_por_competencia(self):
        wh = self.tmp / "e.duckdb"
        criar_warehouse(wh, com_reconciliado=True)
        b = boletim.carregar(wh, "202607")
        self.assertEqual({s["competencia"]: s["situacao"] for s in b.serie},
                         {"202506": "consolidado", "202605": "provisório", "202606": "provisório", "202607": "provisório"})

    def test_gera_pdf_e_xlsx_com_a_reconciliacao(self):
        wh = self.tmp / "f.duckdb"
        criar_warehouse(wh, com_reconciliado=True)
        pdf, xlsx = boletim.gerar(wh, "202607", self.tmp / "s")
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))
        textos = zipfile.ZipFile(xlsx).read("xl/sharedStrings.xml").decode()
        for esperado in ("Saldo só-MOV (no prazo)", "Efeito das exclusões", "Situação", "provisório", "reconciliado"):
            self.assertIn(esperado, textos)

    def test_comparacao_com_o_mesmo_mes_do_ano_anterior_alem_da_janela_do_grafico(self):
        """Regressão: o mesmo mês do ano anterior está a 13 meses, fora dos 12 do gráfico."""
        wh = self.tmp / "h.duckdb"
        con = duckdb.connect(str(wh))
        con.execute(
            "create table mart_caged_mensal_grupamento (competencia_mov bigint, grupamento varchar, "
            "admissoes bigint, desligamentos bigint, saldo_liquido hugeint, admissoes_com_salario_valido bigint, "
            "salario_mediano_admissao double, salario_medio_admissao double, palma_index_admissao double)"
        )
        comp = "202506"
        while comp <= "202607":
            con.execute("insert into mart_caged_mensal_grupamento values (?,?,?,?,?,?,?,?,?)",
                        [int(comp), "Comércio", 100, 90, 10 if comp == "202507" else 5, 95, 1650.0, 1800.0, 2.1])
            comp = boletim.competencia_deslocada(comp, 1)
        con.close()
        b = boletim.carregar(wh, "202607")
        self.assertEqual(len(b.serie), 12)
        self.assertNotIn("202507", [s["competencia"] for s in b.serie])  # fora da janela do gráfico
        resumo = " ".join(boletim._resumo(b))
        self.assertNotIn("indisponível", resumo)
        self.assertIn("mesmo mês do ano anterior (julho/2025): +10", resumo)

    # ------------------------------------------------------------- estoque (F16/F20)

    def _com_estoque(self, nome: str, referencia: bool = True) -> Path:
        """Warehouse reconciliado + mart_estoque. Socorro: Comércio e Serviços com saldo +16/mês
        (como no reconciliado) e Indústria com estoque 500 e NENHUMA movimentação; Não
        Identificado com estoque 0. Sergipe (28) com números maiores, que não podem vazar."""
        wh = self.tmp / nome
        criar_warehouse(wh, com_reconciliado=True)
        con = duckdb.connect(str(wh))
        con.execute(
            "create table mart_estoque (territorio varchar, grupamento varchar, competencia_mov bigint, "
            "saldo_consolidado bigint, estoque hugeint, taxa_variacao_mensal double, competencia_referencia bigint)"
        )
        for i, c in enumerate(("202605", "202606", "202607")):
            for g, base, saldo in (("Comércio", 1000, 16), ("Serviços", 1000, 16), ("Indústria", 500, 0), ("Não Identificado", 0, 0)):
                est = base + saldo * i if referencia else None
                ant = base + saldo * (i - 1) if referencia else None
                taxa = saldo / ant if referencia and i > 0 and ant else None
                con.execute("insert into mart_estoque values ('280480', ?, ?, ?, ?, ?, ?)",
                            [g, int(c), saldo, est, taxa, 202512 if referencia else None])
            con.execute("insert into mart_estoque values ('28', 'Comércio', ?, 999, 90000, 0.5, 202512)", [int(c)])
        con.close()
        return wh

    def test_estoque_e_taxa_no_resumo_na_tabela_e_na_planilha(self):
        wh = self._com_estoque("i.duckdb")
        b = boletim.carregar(wh, "202607")
        self.assertTrue(b.tem_estoque)
        # 1032 + 1032 + 500 (+ 0); taxa do total = 32 / (1016 + 1016 + 500)
        self.assertEqual(b.estoque_total["estoque"], 2564)
        self.assertAlmostEqual(b.estoque_total["taxa_variacao_mensal"], 32 / 2532)
        comercio = next(l for l in b.linhas if l["grupamento"] == "Comércio")
        self.assertEqual(comercio["estoque"], 1032)
        self.assertAlmostEqual(comercio["taxa_variacao_mensal"], 16 / 1016)
        resumo = " ".join(boletim._resumo(b))
        self.assertIn("Estoque estimado ao fim do mês: 2.564 vínculos formais", resumo)
        self.assertIn("+1,26% no mês", resumo)
        self.assertIn("estimativa a partir do estoque de referência do mte", " ".join(boletim._notas(b)).lower())
        pdf, xlsx = boletim.gerar(wh, "202607", self.tmp / "s")
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))
        textos = zipfile.ZipFile(xlsx).read("xl/sharedStrings.xml").decode()
        self.assertIn("Estoque (estimativa, fim do mês)", textos)
        self.assertIn("Variação do estoque no mês", textos)

    def test_grupamento_sem_movimentacao_entra_com_o_estoque(self):
        """Indústria não tem movimentação no mês (fora dos marts de fluxo), mas tem estoque: sem ela a
        coluna de estoque não fecharia com o total."""
        b = boletim.carregar(self._com_estoque("j.duckdb"), "202607")
        ind = next(l for l in b.linhas if l["grupamento"] == "Indústria")
        self.assertEqual((ind["admissoes"], ind["saldo_liquido"], ind["estoque"]), (0, 0, 500))
        self.assertEqual(ind["situacao"], "provisório")  # herdado da competência
        self.assertIsNone(ind["salario_mediano_admissao"])
        self.assertNotIn("Não Identificado", [l["grupamento"] for l in b.linhas])  # estoque 0: não entra
        self.assertEqual(b.total["saldo_liquido"], 34)  # as contagens não mudam
        self.assertEqual(b.total_so_mov, 20)

    def test_sem_mart_estoque_o_boletim_sai_sem_estoque(self):
        wh = self.tmp / "k.duckdb"
        criar_warehouse(wh, com_reconciliado=True)
        b = boletim.carregar(wh, "202607")
        self.assertFalse(b.tem_estoque)
        self.assertNotIn("Estoque", " ".join(boletim._resumo(b)))
        self.assertNotIn("estoque de referência", " ".join(boletim._notas(b)))
        pdf, xlsx = boletim.gerar(wh, "202607", self.tmp / "s")
        self.assertNotIn("Estoque (estimativa", zipfile.ZipFile(xlsx).read("xl/sharedStrings.xml").decode())

    def test_territorio_sem_referencia_gera_o_boletim_sem_estoque(self):
        """Critério 3 da F16: estoque NULL não impede o boletim."""
        wh = self._com_estoque("l.duckdb", referencia=False)
        b = boletim.carregar(wh, "202607")
        self.assertFalse(b.tem_estoque)
        pdf, _ = boletim.gerar(wh, "202607", self.tmp / "s")
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))

    def test_so_o_territorio_do_boletim(self):
        b = boletim.carregar(self._com_estoque("m.duckdb"), "202607")
        self.assertNotIn(90000, [l.get("estoque") for l in b.historico])

    def test_competencia_ausente_do_mart_levanta_erro(self):
        wh = self.tmp / "g.duckdb"
        criar_warehouse(wh, com_reconciliado=True)
        with self.assertRaises(ValueError):
            boletim.carregar(wh, "201901")


if __name__ == "__main__":
    unittest.main()
