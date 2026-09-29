"""
Testes da calibração do Jev (F19 parte 6): casos gerados por código com a verdade conhecida e
a escolha do limiar pelo custo dos erros. Sem rede.

Rodar:
    docker compose run --rm --no-deps -v ./pipeline/tests:/app/tests \\
        --entrypoint python pipeline -m unittest discover -s /app/tests -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "flows"))

import calibracao  # noqa: E402

FATOS = {
    "competencia": "202607",
    "rotulos": {"competencia": "julho de 2026", "ano_anterior": "julho de 2025"},
    "setorial": {"destaques": ["Serviços"], "grupamentos": {
        "Serviços": {"saldo": {"id": "s.serv", "valor": -90}},
        "Comércio": {"saldo": {"id": "s.com", "valor": 11}},
        "Não Identificado": {"saldo": {"id": "s.ni", "valor": 0}}}},
    "panorama": {"sazonalidade": {"posicao": "dentro_da_faixa", "minimo": {"id": "f.min", "valor": -247},
                                  "maximo": {"id": "f.max", "valor": 306}},
                 "decomposicao": {"variacao_admissoes": {"id": "d.adm", "valor": -178}}},
    "comparacao": {"territorio": {"taxa_mes": {"id": "t.mes", "valor": -0.33}},
                   "uf": {"nome": "Sergipe", "taxa_mes": {"id": "u.mes", "valor": 0.31}}},
    "perfil": {"sexo": {"Mulher": {"variacao_participacao_pp": {"id": "p.mul", "valor": -15.63}}}},
}


class Casos(unittest.TestCase):
    def test_verdade_vem_dos_numeros(self):
        casos = {c["texto"]: c["verdade"] for c in calibracao.casos_de_afirmacao(FATOS)}
        self.assertTrue(casos["O saldo de Serviços foi negativo em julho de 2026."])
        self.assertFalse(casos["O saldo de Comércio foi negativo em julho de 2026."])
        self.assertTrue(casos["O saldo do município ficou dentro da faixa histórica de julho."])
        self.assertFalse(casos["O saldo do município ficou abaixo da faixa histórica de julho."])
        self.assertTrue(casos["A variação do estoque no mês foi menor no município do que em Sergipe."])
        self.assertTrue(casos["As admissões caíram em relação a julho de 2025."])
        self.assertFalse(casos["A participação das mulheres nas admissões aumentou."])
        self.assertFalse(any("Não Identificado" in t for t in casos))          # saldo zero não gera caso
        causas = [c for c in calibracao.casos_de_afirmacao(FATOS) if c["familia"] == "causa"]
        self.assertTrue(causas and not any(c["verdade"] for c in causas))    # causa: sempre falsa


class Metricas(unittest.TestCase):
    def test_limiar_pelo_custo_com_falso_positivo_mais_caro(self):
        casos = [{"verdade": True, "probabilidade": 0.9}, {"verdade": True, "probabilidade": 0.55},
                 {"verdade": False, "probabilidade": 0.6}, {"verdade": False, "probabilidade": 0.2}]
        m = calibracao.metricas(casos)
        # 0.7, 0.8 e 0.9 empatam (0 FP, 1 FN, custo 1); 0.5 tem 1 FP (custo 3). Empate: o do meio.
        self.assertEqual(m["limiar_de_menor_custo"]["limiar"], 0.8)
        self.assertEqual(m["limiar_de_menor_custo"]["custo"], 1)
        self.assertEqual(sum(f["casos"] for f in m["confiabilidade"]), 4)


if __name__ == "__main__":
    unittest.main()
