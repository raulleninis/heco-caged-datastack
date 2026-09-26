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

    def test_competencia_ausente_do_mart_levanta_erro(self):
        wh = self.tmp / "g.duckdb"
        criar_warehouse(wh, com_reconciliado=True)
        with self.assertRaises(ValueError):
            boletim.carregar(wh, "201901")


if __name__ == "__main__":
    unittest.main()
