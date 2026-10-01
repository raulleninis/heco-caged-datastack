"""
Testes do estoque de referência do MTE (F20): leitura do zip, detecção de mudança e aviso de ano
novo. Sem rede: o download é uma função passada a `verificar`.

Rodar (a imagem do pipeline já tem as dependências):
    docker compose run --rm --no-deps -v ./pipeline/tests:/app/tests \\
        --entrypoint python pipeline -m unittest discover -s /app/tests -v
"""

import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "flows"))

import estoque_referencia as er  # noqa: E402

CONTEUDO = (
    "codmun;cnae20subclas;estoqueref\n"
    "110001;111302;2\n"            # outra UF: fica de fora
    "280480;151201;19\n"
    "280480;2424502;5\n"
    "280030;4711302;100\n"
)

PAGINA = '<a href=".../estoque-de-referencia-2026.zip/view">2026</a> <a href=".../estoque-de-referencia-2024.zip/view">'


def zip_com(texto: str, nome: str = "EstoquePAE2026CNAExMun.txt") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(nome, texto.encode("latin-1"))
    return buf.getvalue()


def servidor(zip_bytes: bytes | Exception, pagina: str = PAGINA):
    """`baixar` falso: o zip para a URL do arquivo, a página para a da pasta."""
    def baixar(url: str) -> bytes:
        if url == er.URL_PASTA:
            return pagina.encode()
        if isinstance(zip_bytes, Exception):
            raise zip_bytes
        return zip_bytes
    return baixar


class LerZipTest(unittest.TestCase):
    def test_so_a_uf_e_com_o_estoque_inteiro(self):
        arq = er.ler_zip(zip_com(CONTEUDO), 2026)
        self.assertEqual(arq.linhas, [("280480", "151201", 19), ("280480", "2424502", 5), ("280030", "4711302", 100)])
        self.assertEqual(arq.nome, "EstoquePAE2026CNAExMun.txt")
        self.assertEqual(er.competencia_referencia(2026), 202512)

    def test_mesmo_conteudo_em_outro_zip_tem_o_mesmo_hash(self):
        """Decide pelo .txt: o MTE pode refazer o zip sem mudar o dado."""
        a = er.ler_zip(zip_com(CONTEUDO), 2026)
        b = er.ler_zip(zip_com(CONTEUDO, nome="outro.txt"), 2026)
        self.assertEqual(a.sha256, b.sha256)

    def test_formato_inesperado(self):
        for ruim in (b"nao e zip", zip_com("a;b;c\n1;2;3\n"), zip_com("codmun;cnae20subclas;estoqueref\n110001;1;2\n")):
            with self.assertRaises(er.FormatoInesperado):
                er.ler_zip(ruim, 2026)

    def test_anos_publicados(self):
        self.assertEqual(er.anos_publicados(PAGINA), {2024, 2026})


class VerificarTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.wh = self.tmp / "caged.duckdb"
        self.notificar = mock.patch.object(er, "notificar").start()
        self.addCleanup(mock.patch.stopall)

    def _tabela(self):
        con = duckdb.connect(str(self.wh), read_only=True)
        try:
            return sorted(con.execute("select codmun, subclasse, estoque from estoque_referencia").fetchall())
        finally:
            con.close()

    def test_primeira_carga_depois_igual_depois_mudou(self):
        self.assertEqual(er.verificar(self.wh, 2026, servidor(zip_com(CONTEUDO))), "carregado")
        self.assertEqual(len(self._tabela()), 3)
        self.assertEqual(er.verificar(self.wh, 2026, servidor(zip_com(CONTEUDO))), "igual")
        self.notificar.assert_not_called()

        novo = CONTEUDO.replace("280480;2424502;5", "280480;2424502;10")
        self.assertEqual(er.verificar(self.wh, 2026, servidor(zip_com(novo))), "mudou")
        self.assertIn(("280480", "2424502", 10), self._tabela())
        self.assertEqual(len(self._tabela()), 3)  # substitui, não acumula
        self.assertIn("alterado", self.notificar.call_args.args[0])
        con = duckdb.connect(str(self.wh), read_only=True)
        self.assertEqual(con.execute("select count(*) from estoque_referencia_arquivos").fetchone()[0], 2)
        con.close()

    def test_indisponivel_nao_derruba_e_mantem_o_carregado(self):
        er.verificar(self.wh, 2026, servidor(zip_com(CONTEUDO)))
        self.assertEqual(er.verificar(self.wh, 2026, servidor(OSError("HTTP 403"))), "indisponivel")
        self.assertEqual(len(self._tabela()), 3)
        self.assertIn("já carregado", self.notificar.call_args.args[1])

    def test_indisponivel_na_primeira_vez_deixa_a_tabela_vazia(self):
        """O dbt lê a tabela como source: ela tem de existir mesmo sem dado."""
        self.assertEqual(er.verificar(self.wh, 2026, servidor(OSError("timeout"))), "indisponivel")
        self.assertEqual(self._tabela(), [])

    def test_ano_novo_avisa_uma_vez(self):
        pagina = PAGINA + '<a href=".../estoque-de-referencia-2027.zip/view">'
        er.verificar(self.wh, 2026, servidor(zip_com(CONTEUDO), pagina))
        er.verificar(self.wh, 2026, servidor(zip_com(CONTEUDO), pagina))
        avisos = [c for c in self.notificar.call_args_list if "2027" in c.args[0]]
        self.assertEqual(len(avisos), 1)


if __name__ == "__main__":
    unittest.main()
