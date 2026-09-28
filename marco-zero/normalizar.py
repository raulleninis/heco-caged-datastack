"""Normaliza os originais do painel MTE: marco zero (um CSV por território) e validação.

Uso: python3 marco-zero/normalizar.py (só biblioteca padrão; sobrescreve estoque/ e validacao/*_estoque_painel.csv).
"""
import csv
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent

TERRITORIOS = {  # nome no painel -> (código, slug do arquivo)
    "Nossa Senhora do Socorro": ("280480", "nossa_senhora_do_socorro"),
    "Aracaju": ("280030", "aracaju"),
    "Barra dos Coqueiros": ("280060", "barra_dos_coqueiros"),
    "São Cristóvão": ("280670", "sao_cristovao"),
    "Sergipe": ("28", "sergipe"),
}
GRUPAMENTOS = ["Agropecuária", "Indústria", "Construção", "Comércio", "Serviços", "Não Identificado"]
FONTE = (
    "Painel Novo CAGED (MTE, Power BI), estoque ao fim de mar/2020 por grande grupamento, "
    "já consolidado com declarações fora do prazo e exclusões até a atualização do painel "
    "de 28/08/2026 (última competência 202607). Metodologia do Novo CAGED. Ver marco-zero/FONTE.md"
)
DATA_REFERENCIA = "2020-03-31"
RETIFICACOES_ATE = "202607"  # último arquivo FOR/EXC já incorporado pelo painel na coleta
COLETADO_EM = "2026-09-28"


def ler_painel(caminho):
    """{(regiao, competencia): {grupamento: estoque}} conferindo soma = TOTAL.

    O painel esconde "Não Identificado" quando ele é zero ou NEGATIVO (célula vazia ou linha
    ausente), mas o TOTAL o inclui: nesse caso ele é derivado como TOTAL − os outros cinco
    (em Sergipe chega a −4). Quando vem preenchido, a soma é conferida. Os outros cinco
    grupamentos são obrigatórios."""
    dados = defaultdict(dict)
    with caminho.open(encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            estoque = r["estoque"].strip()
            dados[(r["regiao"], r["competencia"])][r["grupamento"].strip()] = int(estoque) if estoque else None
    saida = {}
    for chave, g in dados.items():
        total = g.pop("TOTAL")
        assert set(g) <= set(GRUPAMENTOS), (chave, set(g) - set(GRUPAMENTOS))
        cinco = GRUPAMENTOS[:-1]
        assert all(g.get(k) is not None for k in cinco), (chave, g)
        valores = {k: g[k] for k in cinco}
        ni = total - sum(valores.values())
        if g.get("Não Identificado") is not None:
            assert g["Não Identificado"] == ni, (chave, g["Não Identificado"], ni)
        valores["Não Identificado"] = ni
        saida[chave] = valores
    return saida


# Marco zero: um arquivo por território
marco = ler_painel(BASE / "Caged Mar 2020.csv")
assert {r for r, _ in marco} == set(TERRITORIOS) and {c for _, c in marco} == {"202003"}
(BASE / "estoque").mkdir(exist_ok=True)
for nome, (codigo, slug) in TERRITORIOS.items():
    with (BASE / "estoque" / f"{codigo}_{slug}.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["territorio", "grupamento", "estoque", "data_referencia", "retificacoes_ate", "fonte", "coletado_em"])
        for k, v in marco[(nome, "202003")].items():
            w.writerow([codigo, k, v, DATA_REFERENCIA, RETIFICACOES_ATE, FONTE, COLETADO_EM])
    print(f"marco zero {codigo:>6} {nome:<26} ok")

# Validação: estoque do painel em meses posteriores, um arquivo por território
valid = ler_painel(BASE / "validacao" / "Caged Estoque 2020-2026 v2.csv")
assert {r for r, _ in valid} == set(TERRITORIOS)
for nome, (codigo, slug) in TERRITORIOS.items():
    comps = sorted(c for r, c in valid if r == nome)
    with (BASE / "validacao" / f"{codigo}_estoque_painel.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["territorio", "grupamento", "competencia", "estoque", "retificacoes_ate", "coletado_em"])
        for comp in comps:
            for k, v in valid[(nome, comp)].items():
                w.writerow([codigo, k, comp, v, RETIFICACOES_ATE, COLETADO_EM])
    print(f"validação {codigo:>6} {nome:<26} {len(comps)} competências ok")
