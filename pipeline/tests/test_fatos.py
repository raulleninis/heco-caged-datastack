"""
Testes dos fatos do boletim com IA (F19 parte 1): cálculos do panorama, gatilhos,
desagregação, comparação regional, perfil e o registro de números do verificador.

Rodar (a imagem do pipeline já tem as dependências):
    docker compose run --rm --no-deps -v ./pipeline/tests:/app/tests \\
        --entrypoint python pipeline -m unittest discover -s /app/tests -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "flows"))

import fatos  # noqa: E402

MUN, UF, OUTRO = "280480", "28", "280030"
GRUPAMENTOS = ("Comércio", "Indústria", "Serviços")


def criar_warehouse(caminho: Path, servicos_jul_2026: int = -120) -> None:
    """Warehouse mínimo com os marts que fatos.py lê. Série de 2021-01 a 2026-07.

    Cada grupamento tem 100 admissões e 95 desligamentos por mês (saldo +5). Em 2026-07, no
    município, Serviços tem saldo `servicos_jul_2026`: o subgrupamento 'Informação' (divisão
    82) com 30 admissões e o resto do saldo em desligamentos, mais 'Transporte' com +30.
    """
    con = duckdb.connect(str(caminho))
    con.execute("create table territorios (territorio varchar, nome varchar, tipo varchar, ativo boolean)")
    con.execute("insert into territorios values (?,?,?,?),(?,?,?,?),(?,?,?,?)",
                [MUN, "Município A", "municipio", True, OUTRO, "Município B", "municipio", True,
                 UF, "Estado", "uf", True])
    con.execute("create table regioes (regiao varchar, nome varchar, territorio varchar)")
    con.execute("insert into regioes values ('RM','Região Teste',?),('RM','Região Teste',?)", [MUN, OUTRO])
    con.execute("create table mart_fluxo (territorio varchar, competencia_mov bigint, grupamento varchar, "
                "subgrupamento varchar, divisao_cnae varchar, divisao_descricao varchar, "
                "admissoes bigint, desligamentos bigint, saldo bigint)")
    comps = [a * 100 + m for a in range(2021, 2027) for m in range(1, 13) if a * 100 + m <= 202607]
    linhas = []
    for t in (MUN, OUTRO, UF):
        for c in comps:
            for g in GRUPAMENTOS:
                if t == MUN and c == 202607 and g == "Serviços":
                    saldo_info = servicos_jul_2026 - 30
                    linhas.append((t, c, g, "Informação", "82", "Serviços de escritório", 30, 30 - saldo_info, saldo_info))
                    linhas.append((t, c, g, "Transporte", "49", "Transporte terrestre", 70, 40, 30))
                    continue
                sub = "Informação" if g == "Serviços" else g
                linhas.append((t, c, g, sub, "82" if g == "Serviços" else "47", "Divisão", 100, 95, 5))
    con.executemany("insert into mart_fluxo values (?,?,?,?,?,?,?,?,?)", linhas)

    con.execute("create table mart_estoque as select territorio, grupamento, competencia_mov, "
                "sum(saldo) as saldo_consolidado from mart_fluxo group by 1, 2, 3")
    con.execute("alter table mart_estoque add column estoque bigint")
    con.execute("alter table mart_estoque add column taxa_variacao_mensal double")
    con.execute("""update mart_estoque e set estoque = 10000 + s.acum from (
        select territorio, grupamento, competencia_mov,
               sum(saldo_consolidado) over (partition by territorio, grupamento order by competencia_mov) acum
        from mart_estoque) s
        where s.territorio = e.territorio and s.grupamento = e.grupamento and s.competencia_mov = e.competencia_mov""")
    con.execute("""update mart_estoque e set taxa_variacao_mensal = e.saldo_consolidado / s.ant from (
        select territorio, grupamento, competencia_mov,
               lag(estoque) over (partition by territorio, grupamento order by competencia_mov) ant
        from mart_estoque) s
        where s.territorio = e.territorio and s.grupamento = e.grupamento and s.competencia_mov = e.competencia_mov""")
    con.execute("""create table mart_estoque_regiao as
        select 'RM' regiao, 'Região Teste' nome, grupamento, competencia_mov,
               sum(saldo_consolidado) saldo_consolidado, sum(estoque) estoque, null::double taxa_variacao_mensal
        from mart_estoque where territorio in (?, ?) group by 1, 2, 3, 4""", [MUN, OUTRO])

    con.execute("create table mart_perfil_movimentacoes (territorio varchar, competencia_mov bigint, "
                "dimensao varchar, categoria varchar, admissoes bigint, desligamentos bigint, saldo bigint)")
    for c in (202507, 202607):
        con.execute("insert into mart_perfil_movimentacoes values (?,?,?,?,?,?,?),(?,?,?,?,?,?,?),(?,?,?,?,?,?,?)",
                    [MUN, c, "sexo", "Homem", 180, 150, 30, MUN, c, "sexo", "Mulher", 100, 140, -40,
                     MUN, c, "faixa_etaria", "65 ou mais", 5, 3, 2])
    con.execute("create table mart_salario_admissao (territorio varchar, competencia_mov bigint, "
                "admissoes_com_salario_valido bigint, salario_mediano_admissao double, salario_medio_admissao double)")
    con.execute("insert into mart_salario_admissao values (?,?,?,?,?),(?,?,?,?,?)",
                [MUN, 202607, 250, 1661.0, 1808.87, MUN, 202507, 240, 1518.0, 1700.0])
    con.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.wh = self.dir / "w.duckdb"
        self.perfis = self.dir / "perfis"
        self.perfis.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def gerar(self, **kw):
        criar_warehouse(self.wh, **kw)
        return fatos.gerar_fatos(self.wh, MUN, "202607", perfis=self.perfis)


class Utilidades(unittest.TestCase):
    def test_deslocar_atravessa_o_ano(self):
        self.assertEqual(fatos.deslocar(202601, -1), 202512)
        self.assertEqual(fatos.deslocar(202607, -12), 202507)
        self.assertEqual(fatos.deslocar(202512, 1), 202601)
        self.assertEqual(fatos.meses_entre(202507, 202607), 12)

    def test_sazonalidade_usa_faixa_e_exige_anos(self):
        self.assertEqual(fatos.sazonalidade(50, {2023: 10, 2024: 20, 2025: 30}, 3)["posicao"], "acima_da_faixa")
        self.assertEqual(fatos.sazonalidade(20, {2023: 10, 2024: 20, 2025: 30}, 3)["posicao"], "dentro_da_faixa")
        self.assertEqual(fatos.sazonalidade(-5, {2023: 10, 2024: 20, 2025: 30}, 3)["posicao"], "abaixo_da_faixa")
        self.assertEqual(fatos.sazonalidade(50, {2024: 20, 2025: 30}, 3)["posicao"], "historico_insuficiente")

    def test_limiar_desconhecido_no_perfil_e_erro(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "1.toml").write_text("[limiares]\nlimiar_inventado = 3\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                fatos.carregar_limiares("1", Path(d))


class Panorama(Base):
    def test_totais_acumulados_e_estoque(self):
        f = self.gerar()
        p = f["panorama"]
        # julho/2026: Comércio +5, Indústria +5, Serviços −120 -> saldo −110
        self.assertEqual(p["saldo"]["valor"], -110)
        self.assertEqual(p["admissoes"]["valor"], 300)
        self.assertEqual(p["mesmo_mes_ano_anterior"]["saldo"]["valor"], 15)
        # jan–jun/2026 a +15 por mês, julho −110
        self.assertEqual(p["acumulado_ano"]["valor"], 6 * 15 - 110)
        self.assertEqual(p["acumulado_12_meses"]["valor"], 11 * 15 - 110)
        self.assertIsNotNone(p["estoque"]["valor"])
        self.assertTrue(f["provisorio"])

    def test_motor_da_variacao(self):
        # admissões iguais (300 x 300); desligamentos sobem de 285 para 410: motor = desligamentos
        f = self.gerar()
        d = f["panorama"]["decomposicao"]
        self.assertEqual(d["variacao_admissoes"]["valor"], 0)
        self.assertEqual(d["motor"], "desligamentos")
        self.assertEqual(d["variacao_saldo"]["valor"], -125)

    def test_sazonalidade_do_total(self):
        f = self.gerar()
        self.assertEqual(f["panorama"]["sazonalidade"]["posicao"], "abaixo_da_faixa")
        self.assertIn("sazonal_total", [g["tipo"] for g in f["gatilhos"]])


class Setorial(Base):
    def test_destaque_contribuicao_e_desagregacao(self):
        f = self.gerar()
        s = f["setorial"]
        self.assertEqual(s["destaques"], ["Serviços"])
        self.assertAlmostEqual(s["grupamentos"]["Serviços"]["contribuicao_saldo"]["valor"], 109.09, places=2)
        d = f["desagregacao"]
        self.assertEqual(len(d), 1)
        self.assertEqual((d[0]["nivel"], d[0]["codigo"]), ("subgrupamento", "Informação"))
        self.assertEqual(d[0]["saldo"]["valor"], -150)

    def test_saldo_perto_de_zero_nao_calcula_contribuicao(self):
        f = self.gerar(servicos_jul_2026=-5)  # total = 5 + 5 − 5 = 5
        self.assertNotIn("contribuicao_saldo", f["setorial"]["grupamentos"]["Serviços"])
        self.assertIn("saldo_total_perto_de_zero", [g["tipo"] for g in f["gatilhos"]])
        self.assertEqual(f["setorial"]["destaques"], [])


class ComparacaoPerfilSalario(Base):
    def test_regiao_e_uf(self):
        c = self.gerar()["comparacao"]
        self.assertEqual(c["territorio"]["nome"], "Município A")
        self.assertEqual([r["nome"] for r in c["regioes"]], ["Região Teste"])
        self.assertEqual(c["uf"]["nome"], "Estado")
        self.assertIsNone(c["brasil"])

    def test_base_pequena_no_perfil(self):
        f = self.gerar()
        self.assertTrue(f["perfil"]["faixa_etaria"]["65 ou mais"]["base_pequena"])
        self.assertFalse(f["perfil"]["sexo"]["Homem"]["base_pequena"])
        self.assertIn("base_pequena_perfil", [g["tipo"] for g in f["gatilhos"]])

    def test_salario_com_mediana_e_media(self):
        s = self.gerar()["salario"]
        self.assertEqual(s["mediana"]["valor"], 1661.0)
        self.assertEqual(s["media"]["valor"], 1808.87)
        self.assertEqual(s["mediana_ano_anterior"]["valor"], 1518.0)


class Registro(Base):
    def test_todo_numero_das_secoes_esta_no_registro(self):
        f = self.gerar()
        achados = []

        def varrer(x):
            if isinstance(x, dict):
                if {"id", "valor", "unidade"} <= set(x):
                    achados.append(x)
                for v in x.values():
                    varrer(v)
            elif isinstance(x, list):
                for v in x:
                    varrer(v)

        varrer({k: v for k, v in f.items() if k != "numeros"})
        self.assertTrue(achados)
        for a in achados:
            self.assertEqual(f["numeros"][a["id"]]["valor"], a["valor"])

    def test_hash_e_deterministico_e_json_serializavel(self):
        criar_warehouse(self.wh)
        a = fatos.gerar_fatos(self.wh, MUN, "202607", perfis=self.perfis)
        b = fatos.gerar_fatos(self.wh, MUN, "202607", perfis=self.perfis)
        self.assertEqual(a["hash"], b["hash"])
        json.dumps(a, ensure_ascii=False)

    def test_perfil_do_territorio_sobrescreve_limiar(self):
        (self.perfis / f"{MUN}.toml").write_text("[limiares]\ndestaque_min_abs = 500\n", encoding="utf-8")
        f = self.gerar()
        self.assertEqual(f["limiares"]["destaque_min_abs"], 500)
        self.assertEqual(f["setorial"]["destaques"], [])

    def test_territorio_ou_competencia_ausente_e_erro(self):
        criar_warehouse(self.wh)
        with self.assertRaises(ValueError):
            fatos.gerar_fatos(self.wh, "999999", "202607", perfis=self.perfis)
        with self.assertRaises(ValueError):
            fatos.gerar_fatos(self.wh, MUN, "202608", perfis=self.perfis)


if __name__ == "__main__":
    unittest.main()
