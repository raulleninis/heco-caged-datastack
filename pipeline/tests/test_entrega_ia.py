"""
Testes da revisão, aprovação e envio do boletim com IA (F19 parte 5). Sem rede: o remoto do
arquivo é um repositório git bare local e o SMTP é um dublê (os mesmos da F15).

Rodar:
    docker compose run --rm --no-deps -v ./pipeline/tests:/app/tests \\
        --entrypoint python pipeline -m unittest discover -s /app/tests -v
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "flows"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import entrega  # noqa: E402
import entrega_ia  # noqa: E402
from arquivo import Arquivo  # noqa: E402
from test_entrega import DESTINATARIOS, SMTPFalso, git  # noqa: E402

ADMINS = ["chefe@exemplo.com", "analista@exemplo.com"]
RESULTADO = {
    "territorio": "280480", "competencia": "202607", "gerado_em": "2026-09-29T05:00:00+00:00",
    "situacao": "aguardando_aprovacao", "versoes_do_redator": 1, "modelos": {"redator": "x"},
    "verificador": [], "avisos_de_estilo": [],
    "parecer_revisor": {"resumo": "ok", "problemas": []},
    "boletim": {"titulo": "Emprego formal em julho de 2026", "sintese": "Perda de 83 vínculos.",
                "panorama": ["Panorama."], "setores": ["Setores."], "contexto_regional": ["Contexto."],
                "perfil_e_remuneracao": ["Perfil."], "pontos_de_atencao": ["Acompanhar Serviços."],
                "nota_metodologica": "Dados provisórios."},
}
FATOS = {"competencia": 202607, "territorio": {"codigo": "280480", "nome": "Socorro", "tipo": "municipio"},
         "provisorio": True, "rotulos": {"competencia": "julho de 2026", "ano_anterior": "julho de 2025"},
         "panorama": {"saldo": {"valor": -83}, "admissoes": {"valor": 1000}, "desligamentos": {"valor": 1083},
                      "estoque": {"valor": 25439}, "taxa_mes": {"valor": -0.33}},
         "setorial": {"grupamentos": {"Serviços": {"saldo": {"valor": -90}, "admissoes": {"valor": 370},
                                                   "desligamentos": {"valor": 460}, "estoque": {"valor": 10907},
                                                   "taxa_mes": {"valor": -0.82}}}},
         "comparacao": {"territorio": {"nome": "Socorro", "saldo": {"valor": -83}, "estoque": {"valor": 25439},
                                       "taxa_mes": {"valor": -0.33}, "taxa_12_meses": {"valor": 0.75}},
                        "regioes": [], "uf": None}}


class EntregaIATest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.remoto = self.tmp / "remoto.git"
        git("init", "--bare", "--initial-branch=main", str(self.remoto), cwd=self.tmp)
        semente = self.tmp / "semente"
        (semente / "public" / "2026-07").mkdir(parents=True)
        (semente / "public" / "login.html").write_text("login")
        git("init", "--initial-branch=main", cwd=semente)
        git("add", "-A", cwd=semente)
        git("commit", "-m", "esqueleto", cwd=semente)
        git("push", str(self.remoto), "main", cwd=semente)

        self.lista = self.tmp / "destinatarios.txt"
        self.lista.write_text("\n".join(DESTINATARIOS) + "\n", encoding="utf-8")
        self.admins = self.tmp / "admins.txt"
        self.admins.write_text("\n".join(ADMINS) + "\n", encoding="utf-8")
        self.cfg = entrega.Config(
            arquivo=Arquivo(repo_url=str(self.remoto), diretorio=self.tmp / "clone", branch="main"),
            smtp_host="smtp.exemplo.com", smtp_port=587, smtp_user="", smtp_password="",
            remetente="Boletim <boletim@exemplo.com>", sair_da_lista="sair@exemplo.com",
            email_teste="eu@exemplo.com", destinatarios_arquivo=self.lista, site_url="https://arquivo.exemplo.com")
        self.base = self.tmp / "ia"
        self.pasta = self.base / "boletins" / "280480_202607" / "abc"
        self.pasta.mkdir(parents=True)
        self.escrever_resultado(RESULTADO)
        (self.pasta / "fatos.json").write_text(json.dumps(FATOS), encoding="utf-8")
        for modulo in (entrega_ia,):
            p = mock.patch.object(modulo, "notificar", lambda *a, **kw: None)
            p.start()
            self.addCleanup(p.stop)

    def escrever_resultado(self, r):
        (self.pasta / "resultado.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")

    def revisar(self, smtp=None):
        return entrega_ia.revisar("280480", "202607", cfg=self.cfg, smtp_factory=smtp or SMTPFalso(),
                                  base=self.base, admins=self.admins)

    def enviar(self, smtp):
        return entrega_ia.enviar("280480", "202607", cfg=self.cfg, smtp_factory=smtp, base=self.base)

    def test_revisao_vai_so_aos_admins_com_pdf_e_relatorio(self):
        smtp = SMTPFalso()
        self.revisar(smtp)
        self.assertEqual([m["To"] for m in smtp.enviadas], ADMINS)
        msg = smtp.enviadas[0]
        self.assertTrue(msg["Subject"].startswith("[REVISÃO]"))
        anexos = [a.get_filename() for a in msg.iter_attachments()]
        self.assertEqual(anexos, ["boletim-ia-202607.pdf", "revisao.txt"])
        self.assertIsNone(msg["List-Unsubscribe"])  # não é envio da lista
        self.assertEqual(entrega_ia.ler_estado(self.pasta)["status"], "em_revisao")

    def test_fluxo_completo_envia_o_mesmo_pdf_e_e_idempotente(self):
        self.revisar()
        aprovado = entrega_ia.aprovar("280480", "202607", "Fulana", base=self.base)
        self.assertEqual(aprovado["aprovado_por"], "Fulana")
        smtp = SMTPFalso()
        self.assertEqual(self.enviar(smtp), "enviado")
        self.assertEqual([m["To"] for m in smtp.enviadas], DESTINATARIOS)
        pdf_revisado = (self.pasta / "boletim-ia-202607.pdf").read_bytes()
        enviado = next(smtp.enviadas[0].iter_attachments()).get_content()
        self.assertEqual(enviado, pdf_revisado)
        self.assertEqual(self.enviar(SMTPFalso()), "ja_enviado")
        # arquivado e listado no índice, sem mexer no estado do boletim normal
        clone = self.tmp / "clone"
        self.assertTrue((clone / "public" / "2026-07" / "boletim-ia-202607.pdf").exists())
        self.assertIn("boletim com análise (PDF)", (clone / "public" / "index.html").read_text())
        envios = json.loads((clone / "envios.json").read_text())
        self.assertEqual(set(envios), {"ia-202607"})
        self.assertEqual(envios["ia-202607"]["aprovado_por"], "Fulana")

    def test_nao_aprova_sem_revisao_nem_envia_sem_aprovacao(self):
        with self.assertRaises(entrega_ia.RevisaoRecusada):
            entrega_ia.aprovar("280480", "202607", "Fulana", base=self.base)
        self.revisar()
        smtp = SMTPFalso()
        with self.assertRaises(entrega_ia.RevisaoRecusada):
            self.enviar(smtp)
        self.assertEqual(smtp.enviadas, [])

    def test_pdf_alterado_depois_da_revisao_bloqueia(self):
        self.revisar()
        (self.pasta / "boletim-ia-202607.pdf").write_bytes(b"outro pdf")
        with self.assertRaises(entrega_ia.RevisaoRecusada):
            entrega_ia.aprovar("280480", "202607", "Fulana", base=self.base)

    def test_reprovado_no_verificador_nao_vai_a_revisao(self):
        self.escrever_resultado({**RESULTADO, "situacao": "reprovado_no_verificador"})
        smtp = SMTPFalso()
        with self.assertRaises(entrega_ia.RevisaoRecusada):
            self.revisar(smtp)
        self.assertEqual(smtp.enviadas, [])

    def test_relatorio_mostra_avisos_ou_ausencia_da_projecao(self):
        r = {"situacao": "aguardando_aprovacao", "versoes_do_redator": 1, "modelos": {}, "verificador": [],
             "parecer_revisor": {"resumo": "ok", "problemas": []}}
        pr = {"revisao": {"origem": "recalculada"}, "avisos": ["Nenhuma edição anterior publicada."],
              "backtest": {"n_origens": 44, "mae": {"comb": {"S12": 591}, "ingenuo": {"S12": 623}}}}
        texto = entrega_ia._relatorio_de_revisao(r, {"projecao": pr})
        self.assertIn("PROJEÇÃO (Perspectivas, experimental): revisão recalculada", texto)
        self.assertIn("- Nenhuma edição anterior publicada.", texto)
        self.assertIn("FORA DO BOLETIM: sem âncora",
                      entrega_ia._relatorio_de_revisao(r, {"projecao_ausente": "sem âncora"}))

    def test_aprovacao_exige_nome(self):
        self.revisar()
        with self.assertRaises(entrega_ia.RevisaoRecusada):
            entrega_ia.aprovar("280480", "202607", "  ", base=self.base)

    def test_queda_no_envio_deixa_orfao_sem_reenvio(self):
        self.revisar()
        entrega_ia.aprovar("280480", "202607", "Fulana", base=self.base)
        with self.assertRaises(entrega.EnvioInterrompido):
            self.enviar(SMTPFalso(falha_no=2))
        self.assertEqual(self.enviar(SMTPFalso()), "orfao")


if __name__ == "__main__":
    unittest.main()
