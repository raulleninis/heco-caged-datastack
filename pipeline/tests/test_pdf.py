"""
Testes da apresentação dos PDFs (pdf_design, pdf_automatico, pdf_analitico): identidade da
instância vinda do perfil, fontes e logo embutidos, glifos, paginação e casos de borda.

Rodar:
    docker compose run --rm --no-deps -v ./pipeline/tests:/app/tests \\
        --entrypoint python pipeline -m unittest discover -s /app/tests -v
"""

import copy
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "flows"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import boletim  # noqa: E402
import pdf_analitico  # noqa: E402
import pdf_design  # noqa: E402
from test_boletim import criar_warehouse  # noqa: E402


def v(valor):
    return {"valor": valor}


RESULTADO = {
    "territorio": "280480", "competencia": "202607",
    "boletim": {"titulo": "Emprego formal em julho de 2026 — “teste”", "sintese": "Perda de 84 vínculos.",
                "panorama": ["Primeiro parágrafo.", "Segundo parágrafo."], "setores": ["Setores."],
                "contexto_regional": ["Contexto."], "perfil_e_remuneracao": ["Perfil."],
                "pontos_de_atencao": ["Acompanhar Serviços."], "nota_metodologica": "Dados provisórios."},
}
FATOS = {
    "competencia": 202607, "territorio": {"codigo": "280480", "nome": "Socorro", "tipo": "municipio"},
    "provisorio": True, "rotulos": {"competencia": "julho de 2026", "ano_anterior": "julho de 2025"},
    "panorama": {"saldo": v(-84), "admissoes": v(884), "desligamentos": v(968), "estoque": v(25439),
                 "taxa_mes": v(-0.33),
                 "mesmo_mes_ano_anterior": {"saldo": v(103), "admissoes": v(1060), "desligamentos": v(957)},
                 "sazonalidade": {"minimo": v(-247), "maximo": v(306), "anos": [2020, 2021, 2022]}},
    "setorial": {"destaques": ["Serviços"], "grupamentos": {
        "Serviços": {"saldo": v(-88), "admissoes": v(372), "desligamentos": v(460), "estoque": v(10913),
                     "taxa_mes": v(-0.80)},
        "Comércio": {"saldo": v(11), "admissoes": v(262), "desligamentos": v(251), "estoque": v(6623),
                     "taxa_mes": v(0.17)},
        "Não Identificado": {"saldo": v(0), "admissoes": v(0), "desligamentos": v(0), "estoque": v(None),
                             "taxa_mes": v(None)}}},
    "desagregacao": [{"nivel": "subgrupamento", "grupamento": "Serviços", "nome": "Informação e comunicação",
                      "saldo": v(-134), "admissoes": v(128), "desligamentos": v(262),
                      "saldo_ano_anterior": v(72), "saldo_restante_do_grupamento": v(46)}],
    "comparacao": {"territorio": {"nome": "Socorro", "saldo": v(-84), "estoque": v(25439), "taxa_mes": v(-0.33),
                                  "taxa_12_meses": v(0.77)},
                   "regioes": [{"nome": "Região", "saldo": v(910), "estoque": v(236489), "taxa_mes": v(0.39),
                                "taxa_12_meses": v(4.35)}],
                   "uf": None, "brasil": None},
    "perfil": {"sexo": {"Homem": {"participacao_admissoes": v(69.57)}, "Mulher": {"participacao_admissoes": v(30.43)}},
               "faixa_etaria": {"18 a 24": {"participacao_admissoes": v(34.62),
                                            "participacao_admissoes_ano_anterior": v(44.06)}}},
    "salario": {"mediana": v(1661.0), "variacao_nominal_mediana": v(9.42)},
    "indicadores_externos": {"pix": {"competencia": "julho de 2026", "comparado_com": "julho de 2025",
                                     "cuidados": "Valores nominais.",
                                     "recortes": [{"nome": "Socorro", "empresas_recebedoras": v(5184),
                                                   "variacao_empresas_12m": v(21.75),
                                                   "valor_recebido_milhoes": v(789.1), "variacao_valor_12m": v(23.38)}]}},
}


def paginas(pdf: Path) -> int:
    return len(re.findall(rb"/Type /Page\b(?!s)", pdf.read_bytes()))


class IdentidadeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_perfil_da_instancia_traz_nome_instituicao_orgao_e_logo(self):
        i = pdf_design.carregar_identidade("280480")
        self.assertEqual(i.territorio, "Nossa Senhora do Socorro")
        self.assertTrue(i.instituicao and i.orgao)
        self.assertTrue(i.logo.exists())

    def test_sem_perfil_a_identidade_e_neutra(self):
        self.assertEqual(pdf_design.carregar_identidade("999999", self.tmp), pdf_design.Identidade())

    def test_chave_desconhecida_e_logo_ausente_sao_erro(self):
        (self.tmp / "1.toml").write_text('[identidade]\nlogotipo = "x.png"\n', encoding="utf-8")
        with self.assertRaises(ValueError):
            pdf_design.carregar_identidade("1", self.tmp)
        (self.tmp / "2.toml").write_text('[identidade]\nlogo = "nao-existe.png"\n', encoding="utf-8")
        with self.assertRaises(FileNotFoundError):
            pdf_design.carregar_identidade("2", self.tmp)

    def test_neutro_sai_sem_logo_e_com_as_fontes_embutidas(self):
        pdf = pdf_design.BoletimPDF("Neutro")
        pdf.cover("Neutro", "Síntese.")
        destino = self.tmp / "n.pdf"
        pdf.output(str(destino))
        dados = destino.read_bytes()
        self.assertNotIn(b"/Subtype /Image", dados)
        self.assertIn(b"IBMPlexSans", dados)
        self.assertIn(b"Archivo", dados)


class AnaliticoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def gerar(self, resultado=RESULTADO, fatos=FATOS) -> Path:
        (self.tmp / "resultado.json").write_text(json.dumps(resultado, ensure_ascii=False), encoding="utf-8")
        (self.tmp / "fatos.json").write_text(json.dumps(fatos, ensure_ascii=False), encoding="utf-8")
        return pdf_analitico.gerar_pdf(self.tmp, aviso_ia="Texto com apoio de IA.")

    def test_quatro_partes_em_paginas_proprias_sem_glifo_faltando(self):
        with self.assertNoLogs("fpdf", level="WARNING"):
            pdf = self.gerar()
        self.assertEqual(pdf.name, "boletim-ia-202607.pdf")
        self.assertEqual(paginas(pdf), 4)
        self.assertIn(b"/Subtype /Image", pdf.read_bytes())  # logo do perfil 280480

    def test_secao_perspectivas_com_grafico_e_revisao(self):
        """F21: parágrafo, indicadores, gráfico, aviso em destaque e revisão, sem glifo faltando."""
        hist = [{"competencia": f"2025-{m:02d}", "estoque": 25000 + 20 * m} for m in range(1, 13)] + \
               [{"competencia": f"2026-{m:02d}", "estoque": 25200 - 10 * m} for m in range(1, 8)]
        mensal = [{"competencia": c, "admissoes": 900.0, "desligamentos": 880.0, "saldo": 20.0,
                   "estoque": 25130 + 20 * i, "estoque_lo": 25130 + 20 * i - 100 * (i + 1),
                   "estoque_hi": 25130 + 20 * i + 120 * (i + 1)}
                  for i, c in enumerate(["2026-08", "2026-09", "2026-10", "2026-11", "2026-12",
                                         *[f"2027-{m:02d}" for m in range(1, 13)]])]
        fatos = copy.deepcopy(FATOS)
        fatos["projecao"] = {
            "edicao": "2026-07", "ano": 2026, "ano_prox": 2027, "historico": hist, "projecao_mensal": mensal,
            "serie_anterior": {"2026-07": 25150.0, "2026-08": 25200.0, "2026-12": 25400.0},
            "estoque_mes_anterior": 25140.0,
            "kpis": {"estoque_dez_ano": 25210.0, "estoque_dez_ano_faixa": [24710.0, 25810.0], "saldo_ano": -42.0,
                     "saldo_ano_faixa": [-480.0, 600.0], "estoque_dez_prox": 25450.0,
                     "estoque_dez_prox_faixa": [23750.0, 27490.0]},
            "texto": {"paragrafo": "Com base no padrão histórico…", "revisao": "Na edição anterior…",
                      "legenda": "Estoque de vínculos formais, jan/25 a dez/27.",
                      "aviso_experimental": "Projeção experimental: leia com cautela.",
                      "nota_metodologica": "Projeção experimental: média de dois métodos.",
                      "fragilidades": "Fragilidades conhecidas: série curta."}}
        sem = self.gerar().stat().st_size
        with self.assertNoLogs("fpdf", level="WARNING"):
            pdf = self.gerar(fatos=fatos)
        self.assertGreater(pdf.stat().st_size, sem)  # a seção (gráfico, cards, textos) foi desenhada

    def test_grupamentos_em_ordem_alfabetica_com_nao_identificado_por_ultimo(self):
        grupos = {"Serviços": {}, "Não Identificado": {}, "Agropecuária": {}, "Comércio": {}}
        self.assertEqual([n for n, _ in pdf_analitico.ordenar_grupamentos(grupos)],
                         ["Agropecuária", "Comércio", "Serviços", "Não Identificado"])

    def test_blocos_opcionais_ausentes_sao_omitidos(self):
        fatos = copy.deepcopy(FATOS)
        for chave in ("desagregacao", "indicadores_externos", "perfil", "salario"):
            fatos.pop(chave)
        fatos["panorama"].pop("sazonalidade")
        resultado = copy.deepcopy(RESULTADO)
        resultado["boletim"]["pontos_de_atencao"] = []
        self.assertEqual(paginas(self.gerar(resultado, fatos)), 3)

    def test_tabela_longa_e_nome_extenso_continuam_na_pagina_seguinte(self):
        fatos = copy.deepcopy(FATOS)
        grupos = fatos["setorial"]["grupamentos"]
        for n in range(60):
            grupos[f"Grupamento {n}"] = copy.deepcopy(grupos["Comércio"])
        grupos["Nome " + "muito " * 400 + "extenso"] = copy.deepcopy(grupos["Serviços"])
        self.assertGreater(paginas(self.gerar(fatos=fatos)), 5)

    def test_resultado_e_fatos_de_competencias_diferentes_e_erro(self):
        with self.assertRaises(ValueError):
            self.gerar(fatos={**FATOS, "competencia": 202606})


class AutomaticoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_so_mov_e_reconciliado_geram_com_logo_e_sem_glifo_faltando(self):
        for reconciliado in (False, True):
            wh = self.tmp / f"{reconciliado}.duckdb"
            criar_warehouse(wh, com_reconciliado=reconciliado)
            with self.assertNoLogs("fpdf", level="WARNING"):
                pdf, _ = boletim.gerar(wh, "202607", self.tmp / str(reconciliado))
            self.assertIn(b"/Subtype /Image", pdf.read_bytes())
            self.assertGreaterEqual(paginas(pdf), 2)


if __name__ == "__main__":
    unittest.main()
