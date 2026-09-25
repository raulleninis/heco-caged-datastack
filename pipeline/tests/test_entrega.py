"""
Testes da entrega (F15): idempotência, envio órfão, arquivo e reconstrução do warehouse.

Sem rede e sem Prefect rodando: o "remoto" do arquivo é um repositório git bare
local e o SMTP é um dublê. Cobrem os itens 8 a 13 do critério de aceite da F15
(o que depende de Netlify e de um provedor de e-mail reais está no README).

Rodar (a imagem do pipeline já tem as dependências):
    docker compose run --rm --no-deps -v ./pipeline/tests:/app/tests \\
        --entrypoint python pipeline -m unittest discover -s /app/tests -v
"""

import hashlib
import json
import shutil
import smtplib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "flows"))

import entrega  # noqa: E402
from arquivo import Arquivo  # noqa: E402

DESTINATARIOS = ["ana@exemplo.com", "bia@exemplo.com", "caio@exemplo.com"]


def git(*args, cwd):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True,
    )


def criar_mart(caminho: Path, competencias=("202605", "202606", "202607")) -> None:
    con = duckdb.connect(str(caminho))
    con.execute(
        "create table mart_caged_mensal_grupamento (competencia_mov bigint, grupamento varchar, "
        "admissoes bigint, desligamentos bigint, saldo_liquido hugeint, admissoes_com_salario_valido bigint, "
        "salario_mediano_admissao double, salario_medio_admissao double, palma_index_admissao double)"
    )
    for i, c in enumerate(competencias):
        for g, base in (("Comércio", 200), ("Serviços", 300)):
            adm, des = base + i * 10, base - 5 + i
            con.execute(
                "insert into mart_caged_mensal_grupamento values (?,?,?,?,?,?,?,?,?)",
                [int(c), g, adm, des, adm - des, adm - 3, 1650.0, 1800.5, 2.1],
            )
    con.close()


class SMTPFalso:
    """Dublê do smtplib.SMTP: guarda o que 'enviou'; pode falhar no envio nº N."""

    def __init__(self, falha_no=None, recusa=()):
        self.enviadas, self.falha_no, self.recusa = [], falha_no, set(recusa)

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def send_message(self, msg):
        if self.falha_no is not None and len(self.enviadas) + 1 == self.falha_no:
            raise smtplib.SMTPServerDisconnected("conexão caiu")
        if msg["To"] in self.recusa:
            raise smtplib.SMTPRecipientsRefused({msg["To"]: (550, b"no such user")})
        self.enviadas.append(msg)


class EntregaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

        # Remoto do arquivo, já com o esqueleto (o "primeiro deploy").
        self.remoto = self.tmp / "remoto.git"
        git("init", "--bare", "--initial-branch=main", str(self.remoto), cwd=self.tmp)
        semente = self.tmp / "semente"
        (semente / "public").mkdir(parents=True)
        (semente / "public" / "login.html").write_text("login")
        git("init", "--initial-branch=main", cwd=semente)
        git("add", "-A", cwd=semente)
        git("commit", "-m", "esqueleto", cwd=semente)
        git("push", str(self.remoto), "main", cwd=semente)

        self.warehouse = self.tmp / "caged.duckdb"
        criar_mart(self.warehouse)
        self.lista = self.tmp / "destinatarios.txt"
        self.lista.write_text("# lista\n" + "\n".join(DESTINATARIOS) + "\n", encoding="utf-8")
        self.cfg = self.config()

        self.alertas = []
        patcher = mock.patch.object(entrega, "notificar", lambda t, m, prioridade="default": self.alertas.append(t))
        patcher.start()
        self.addCleanup(patcher.stop)

    def config(self, clone="clone"):
        return entrega.Config(
            arquivo=Arquivo(repo_url=str(self.remoto), diretorio=self.tmp / clone, branch="main"),
            smtp_host="smtp.exemplo.com", smtp_port=587, smtp_user="", smtp_password="",
            remetente="Boletim <boletim@exemplo.com>", sair_da_lista="sair@exemplo.com",
            email_teste="eu@exemplo.com", destinatarios_arquivo=self.lista,
            site_url="https://arquivo.exemplo.com", warehouse=self.warehouse,
        )

    def envios_no_remoto(self) -> dict:
        clone = self.tmp / "inspecao"
        shutil.rmtree(clone, ignore_errors=True)
        git("clone", "--branch", "main", str(self.remoto), str(clone), cwd=self.tmp)
        arq = clone / "envios.json"
        return json.loads(arq.read_text()) if arq.exists() else {}

    # ---- 9: rodar duas vezes gera um único envio -------------------------------
    def test_duas_execucoes_geram_um_unico_envio(self):
        smtp = SMTPFalso()
        self.assertEqual(entrega.entregar("202607", cfg=self.cfg, smtp_factory=smtp), "enviado")
        self.assertEqual(len(smtp.enviadas), len(DESTINATARIOS))
        self.assertEqual(entrega.entregar("202607", cfg=self.cfg, smtp_factory=smtp), "ja_enviado")
        self.assertEqual(len(smtp.enviadas), len(DESTINATARIOS))
        self.assertEqual(self.alertas, [])
        e = self.envios_no_remoto()["202607"]
        self.assertEqual((e["status"], e["destinatarios_enviados"]), ("enviado", 3))

    def test_entrega_pendente_pega_so_a_competencia_mais_recente(self):
        smtp = SMTPFalso()
        with mock.patch.object(entrega, "abrir_smtp", side_effect=lambda cfg: smtp()), \
             mock.patch.object(entrega.Config, "do_ambiente", return_value=self.cfg):
            self.assertEqual(entrega.entregar_boletim_pendente.fn(), "enviado")
            self.assertEqual(entrega.entregar_boletim_pendente.fn(), "ja_enviado")
        self.assertEqual(list(self.envios_no_remoto()), ["202607"])  # 202605 e 202606 nunca disparam

    # ---- 8: um e-mail por destinatário, com os anexos corretos -----------------
    def test_mensagem_individual_com_anexos_e_unsubscribe(self):
        smtp = SMTPFalso()
        entrega.entregar("202607", cfg=self.cfg, smtp_factory=smtp)
        for msg, dest in zip(smtp.enviadas, DESTINATARIOS):
            self.assertEqual(msg["To"], dest)  # ninguém vê a lista
            self.assertIn("mailto:sair@exemplo.com", msg["List-Unsubscribe"])
            nomes = [p.get_filename() for p in msg.iter_attachments()]
            self.assertEqual(nomes, ["boletim-202607.pdf", "planilha-202607.xlsx"])
            self.assertTrue(next(msg.iter_attachments()).get_content().startswith(b"%PDF"))

    def test_reply_to_so_quando_configurado(self):
        self.assertIsNone(entrega.montar_mensagem(self.cfg, "a@x.com", "202607", b"%PDF", b"x")["Reply-To"])
        self.cfg.responder_para = "contato@exemplo.com"
        msg = entrega.montar_mensagem(self.cfg, "a@x.com", "202607", b"%PDF", b"x")
        self.assertEqual(msg["Reply-To"], "contato@exemplo.com")

    def test_modo_teste_so_para_o_dono_e_nao_registra_nada(self):
        smtp = SMTPFalso()
        antes = subprocess.run(["git", "rev-parse", "main"], cwd=self.remoto, capture_output=True, text=True).stdout
        self.assertEqual(entrega.entregar("202607", teste=True, cfg=self.cfg, smtp_factory=smtp), "teste")
        self.assertEqual([m["To"] for m in smtp.enviadas], ["eu@exemplo.com"])
        self.assertTrue(smtp.enviadas[0]["Subject"].startswith("[TESTE]"))
        depois = subprocess.run(["git", "rev-parse", "main"], cwd=self.remoto, capture_output=True, text=True).stdout
        self.assertEqual(antes, depois)  # nada arquivado, nada gravado
        self.assertFalse((self.tmp / "clone").exists())

    # ---- 10: queda do SMTP no meio = órfão, sem reenvio, com alerta ------------
    def test_queda_no_meio_deixa_orfao_sem_reenvio_e_alerta(self):
        smtp = SMTPFalso(falha_no=2)
        with self.assertRaises(entrega.EnvioInterrompido):
            entrega.entregar("202607", cfg=self.cfg, smtp_factory=smtp)
        self.assertEqual(len(smtp.enviadas), 1)
        e = self.envios_no_remoto()["202607"]
        self.assertEqual((e["status"], e["destinatarios_enviados"]), ("enviando", 1))
        self.assertIn("conexão caiu", e["erro"])
        self.assertEqual(self.alertas, ["CAGED: envio de boletim INTERROMPIDO"])

        # Próximo run, SMTP já saudável: NÃO reenvia; alerta de novo.
        smtp2 = SMTPFalso()
        self.assertEqual(entrega.entregar("202607", cfg=self.cfg, smtp_factory=smtp2), "orfao")
        self.assertEqual(smtp2.enviadas, [])
        self.assertEqual(self.alertas[-1], "CAGED: envio de boletim ÓRFÃO")
        self.assertEqual(self.envios_no_remoto()["202607"]["status"], "enviando")

    def test_orfao_de_uma_competencia_nao_impede_a_seguinte_mas_alerta(self):
        with self.assertRaises(entrega.EnvioInterrompido):
            entrega.entregar("202606", cfg=self.cfg, smtp_factory=SMTPFalso(falha_no=1))
        smtp = SMTPFalso()
        self.assertEqual(entrega.entregar("202607", cfg=self.cfg, smtp_factory=smtp), "enviado")
        self.assertEqual(len(smtp.enviadas), len(DESTINATARIOS))
        self.assertIn("CAGED: envio de boletim ÓRFÃO", self.alertas)

    def test_destinatario_recusado_nao_derruba_o_envio(self):
        smtp = SMTPFalso(recusa=["bia@exemplo.com"])
        self.assertEqual(entrega.entregar("202607", cfg=self.cfg, smtp_factory=smtp), "enviado")
        self.assertEqual(len(smtp.enviadas), 2)
        e = self.envios_no_remoto()["202607"]
        self.assertEqual((e["status"], e["destinatarios_recusados"]), ("enviado", 1))
        self.assertEqual(self.alertas, ["CAGED: destinatários recusados"])

    def test_push_do_enviando_falha_antes_de_enviar(self):
        """Estado não gravado no remoto => nenhum e-mail sai."""
        smtp = SMTPFalso()
        def falha(self, *a, **kw):
            raise RuntimeError("git push falhou")

        with mock.patch.object(Arquivo, "gravar_estado", falha):
            with self.assertRaises(RuntimeError):
                entrega.entregar("202607", cfg=self.cfg, smtp_factory=smtp)
        self.assertEqual(smtp.enviadas, [])

    def test_remoto_inacessivel_falha_fechado(self):
        cfg = self.config(clone="outro")
        cfg.arquivo.repo_url = str(self.tmp / "nao-existe.git")
        smtp = SMTPFalso()
        with self.assertRaises(RuntimeError):
            entrega.entregar("202607", cfg=cfg, smtp_factory=smtp)
        self.assertEqual(smtp.enviadas, [])

    # ---- 2: o que foi arquivado é o que se envia, mesmo se o dado mudou --------
    def test_reaproveita_o_arquivado_em_vez_de_regenerar(self):
        # Simula um run que morreu entre "arquiva" e "grava enviando".
        pdf, xlsx = self.tmp / "boletim-202607.pdf", self.tmp / "planilha-202607.xlsx"
        pdf.write_bytes(b"%PDF-1.4 versao ja arquivada")
        xlsx.write_bytes(b"xlsx ja arquivado")
        arq = self.cfg.arquivo
        arq.sincronizar()
        arq.arquivar("202607", pdf, xlsx)

        smtp = SMTPFalso()
        entrega.entregar("202607", cfg=self.cfg, smtp_factory=smtp)
        anexo = next(smtp.enviadas[0].iter_attachments()).get_content()
        self.assertEqual(anexo, b"%PDF-1.4 versao ja arquivada")

    # ---- 12: clone do zero confere com os sha256 do envios.json ----------------
    def test_clone_do_zero_confere_os_sha256(self):
        entrega.entregar("202607", cfg=self.cfg, smtp_factory=SMTPFalso())
        clone = self.tmp / "zero"
        git("clone", "--branch", "main", str(self.remoto), str(clone), cwd=self.tmp)
        e = json.loads((clone / "envios.json").read_text())["202607"]
        h = lambda p: hashlib.sha256((clone / "public/2026-07" / p).read_bytes()).hexdigest()  # noqa: E731
        self.assertEqual(h("boletim-202607.pdf"), e["sha256_boletim"])
        self.assertEqual(h("planilha-202607.xlsx"), e["sha256_planilha"])
        self.assertIn("2026-07/boletim-202607.pdf", (clone / "public/index.html").read_text())
        self.assertFalse((clone / "public/envios.json").exists())  # o estado não é publicado

    # ---- 13: apagar e reconstruir o .duckdb não reenvia nada -------------------
    def test_reconstruir_o_warehouse_nao_reenvia(self):
        entrega.entregar("202607", cfg=self.cfg, smtp_factory=SMTPFalso())
        self.warehouse.unlink()
        criar_mart(self.warehouse)  # "reconstruído do zero"
        shutil.rmtree(self.tmp / "clone")  # e o clone local também se perdeu
        smtp = SMTPFalso()
        self.assertEqual(entrega.entregar("202607", cfg=self.config(), smtp_factory=smtp), "ja_enviado")
        self.assertEqual(smtp.enviadas, [])

    # ---- 11: sem competência nova, nenhum e-mail e nenhum alerta ---------------
    def test_sem_competencia_nova_e_silencio(self):
        smtp = SMTPFalso()
        with mock.patch.object(entrega, "abrir_smtp", side_effect=lambda cfg: smtp()), \
             mock.patch.object(entrega.Config, "do_ambiente", return_value=self.cfg):
            entrega.entregar_boletim_pendente.fn()
            n = len(smtp.enviadas)
            for _ in range(3):  # runs diários seguintes: nada novo no FTP
                entrega.entregar_boletim_pendente.fn()
        self.assertEqual(len(smtp.enviadas), n)
        self.assertEqual(self.alertas, [])

    def test_configuracao_incompleta_falha_com_nomes_das_variaveis(self):
        cfg = self.config()
        cfg.smtp_host = ""
        with self.assertRaisesRegex(entrega.ConfigIncompleta, "SMTP_HOST"):
            entrega.entregar("202607", cfg=cfg, smtp_factory=SMTPFalso())

    def test_lista_de_destinatarios_descarta_repetidos_e_invalidos(self):
        self.lista.write_text("a@x.com\nA@X.com\nlixo\n# c\nb@x.com  # fulano\n")
        self.assertEqual(entrega.ler_destinatarios(self.lista), ["a@x.com", "b@x.com"])


if __name__ == "__main__":
    unittest.main()
