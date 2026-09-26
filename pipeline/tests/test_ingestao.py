"""
Testes da ingestão dos três tipos de arquivo (F12): o que está pendente, o registro de
ingestão no warehouse e a leitura dos argumentos do backfill. Sem rede e sem dbt.

Rodar (a imagem do pipeline já tem as dependências):
    docker compose run --rm --no-deps -v ./pipeline/tests:/app/tests \\
        --entrypoint python pipeline -m unittest discover -s /app/tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "flows"))

import ingest_caged as ic  # noqa: E402


def novo_warehouse(tmp: Path, mov=(), staging_for=(), staging_exc=()) -> Path:
    """Warehouse mínimo com as três staging (só as colunas que o flow consulta)."""
    caminho = tmp / "caged.duckdb"
    con = duckdb.connect(str(caminho))
    con.execute("create table stg_caged_movimentacoes (competencia_mov bigint)")
    con.execute("create table stg_caged_fora_do_prazo (competencia_arquivo bigint, competencia_mov bigint)")
    con.execute("create table stg_caged_exclusoes (competencia_arquivo bigint, competencia_mov bigint)")
    for c in mov:
        con.execute("insert into stg_caged_movimentacoes values (?)", [int(c)])
    for arq, m in staging_for:
        con.execute("insert into stg_caged_fora_do_prazo values (?, ?)", [int(arq), int(m)])
    for arq, m in staging_exc:
        con.execute("insert into stg_caged_exclusoes values (?, ?)", [int(arq), int(m)])
    con.close()
    return caminho


class PendentesTest(unittest.TestCase):
    TODOS = {t: set() for t in ic.TIPOS}

    def test_tudo_publicado_e_nada_ingerido(self):
        pub = {"202606": ["MOV", "FOR", "EXC"], "202607": ["MOV", "FOR", "EXC"]}
        self.assertEqual(
            ic._pendentes(pub, self.TODOS),
            [("MOV", "202606"), ("FOR", "202606"), ("EXC", "202606"),
             ("MOV", "202607"), ("FOR", "202607"), ("EXC", "202607")],
        )

    def test_so_o_que_falta_por_tipo(self):
        pub = {"202607": ["MOV", "FOR", "EXC"]}
        ing = {"MOV": {"202607"}, "FOR": set(), "EXC": {"202607"}}
        self.assertEqual(ic._pendentes(pub, ing), [("FOR", "202607")])

    def test_for_que_aparece_depois_do_mov_e_pego(self):
        # 1º run: só o MOV estava publicado. Depois o FOR sai: passa a ser pendente.
        ing = {"MOV": {"202608"}, "FOR": set(), "EXC": set()}
        self.assertEqual(ic._pendentes({"202608": ["MOV"]}, ing), [])
        self.assertEqual(ic._pendentes({"202608": ["MOV", "FOR"]}, ing), [("FOR", "202608")])

    def test_nao_publicado_nao_e_pendente(self):
        self.assertEqual(ic._pendentes({"202609": []}, self.TODOS), [])

    def test_filtro_de_tipos_do_backfill(self):
        pub = {"202607": ["MOV", "FOR", "EXC"]}
        self.assertEqual(ic._pendentes(pub, self.TODOS, ("FOR", "EXC")), [("FOR", "202607"), ("EXC", "202607")])

    def test_ordem_e_da_mais_antiga_para_a_mais_recente(self):
        pub = {"202607": ["MOV"], "202601": ["MOV"], "202603": ["MOV"]}
        self.assertEqual([c for _, c in ic._pendentes(pub, self.TODOS)], ["202601", "202603", "202607"])


class RegistroDeIngestaoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, True))

    def com_warehouse(self, caminho):
        p = mock.patch.object(ic, "WAREHOUSE_PATH", caminho)
        p.start()
        self.addCleanup(p.stop)

    def test_mov_legado_conta_como_ingerido_sem_registro(self):
        # Warehouse anterior à F12: MOV na staging, nenhuma tabela de registro.
        self.com_warehouse(novo_warehouse(self.tmp, mov=[202606, 202607]))
        ing = ic._arquivos_ingeridos()
        self.assertEqual(ing["MOV"], {"202606", "202607"})
        self.assertEqual((ing["FOR"], ing["EXC"]), (set(), set()))

    def test_arquivo_com_zero_linhas_do_municipio_conta_como_ingerido(self):
        """O ponto do registro: um FOR/EXC sem linhas de Socorro não pode ser rebaixado todo dia."""
        self.com_warehouse(novo_warehouse(self.tmp))
        ic._registrar_ingestao("EXC", "202602")  # staging vazia
        self.assertIn("202602", ic._arquivos_ingeridos()["EXC"])
        self.assertEqual(ic._linhas_por_arquivo()[("EXC", "202602")], 0)

    def test_registra_a_contagem_de_linhas_do_arquivo(self):
        self.com_warehouse(novo_warehouse(self.tmp, staging_for=[(202607, 202510), (202607, 202606), (202606, 202605)]))
        ic._registrar_ingestao("FOR", "202607")
        ic._registrar_ingestao("FOR", "202606")
        linhas = ic._linhas_por_arquivo()
        self.assertEqual((linhas[("FOR", "202607")], linhas[("FOR", "202606")]), (2, 1))

    def test_reprocessar_substitui_o_registro(self):
        self.com_warehouse(novo_warehouse(self.tmp, staging_for=[(202607, 202606)]))
        ic._registrar_ingestao("FOR", "202607")
        ic._registrar_ingestao("FOR", "202607")
        con = duckdb.connect(str(self.tmp / "caged.duckdb"), read_only=True)
        self.assertEqual(con.execute("select count(*) from ingestao_arquivos").fetchone()[0], 1)

    def test_warehouse_inexistente_e_nada_ingerido(self):
        self.com_warehouse(self.tmp / "nao-existe.duckdb")
        self.assertEqual(ic._arquivos_ingeridos(), {t: set() for t in ic.TIPOS})
        self.assertEqual(ic._linhas_por_arquivo(), {})


class ArgumentosTest(unittest.TestCase):
    def test_anos(self):
        self.assertEqual(ic._anos_do_argumento("2026"), [2026])
        self.assertEqual(ic._anos_do_argumento("2020..2023"), [2020, 2021, 2022, 2023])


if __name__ == "__main__":
    unittest.main()
