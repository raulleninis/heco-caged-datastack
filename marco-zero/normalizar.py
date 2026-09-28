"""Normaliza os originais do painel MTE: marco zero (um CSV por território) e validação.

Uso (só biblioteca padrão; sobrescreve estoque/ e validacao/*_estoque_painel.csv dos territórios lidos):

    python3 marco-zero/normalizar.py                   originais manuais (Caged Mar 2020.csv e
                                                       validacao/Caged Estoque 2020-2026 v2.csv)
    python3 marco-zero/normalizar.py --coleta PASTA    saída do coletor (marco-zero/coletor), qualquer
                                                       território; código, corte de retificações e data
                                                       da coleta vêm da própria pasta
"""
import argparse
import csv
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent

TERRITORIOS = {  # só para os originais manuais: nome no painel -> (código, slug do arquivo)
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
COMPETENCIA_MARCO = "202003"
RETIFICACOES_ATE = "202607"  # último arquivo FOR/EXC já incorporado pelo painel na coleta
COLETADO_EM = "2026-09-28"


def ler_csv(caminho):
    # utf-8-sig: o coletor grava com BOM (para o Excel abrir acentos); os originais manuais, sem.
    with caminho.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def ler_painel(linhas, chave):
    """{chave(linha): {grupamento: estoque}} conferindo soma = TOTAL.

    O painel esconde "Não Identificado" quando ele é zero ou NEGATIVO (célula vazia ou linha
    ausente), mas o TOTAL o inclui: nesse caso ele é derivado como TOTAL − os outros cinco
    (em Sergipe chega a −4). Quando vem preenchido, a soma é conferida. Os outros cinco
    grupamentos são obrigatórios."""
    dados = defaultdict(dict)
    for r in linhas:
        estoque = r["estoque"].strip()
        dados[chave(r)][r["grupamento"].strip()] = int(estoque) if estoque else None
    saida = {}
    for k, g in dados.items():
        total = g.pop("TOTAL")
        assert total is not None, (k, "TOTAL sem estoque")
        assert set(g) <= set(GRUPAMENTOS), (k, set(g) - set(GRUPAMENTOS))
        cinco = GRUPAMENTOS[:-1]
        assert all(g.get(n) is not None for n in cinco), (k, g)
        valores = {n: g[n] for n in cinco}
        ni = total - sum(valores.values())
        if g.get("Não Identificado") is not None:
            assert g["Não Identificado"] == ni, (k, g["Não Identificado"], ni)
        valores["Não Identificado"] = ni
        saida[k] = valores
    return saida


def slug(nome):
    s = unicodedata.normalize("NFKD", nome.casefold())
    return re.sub(r"[^a-z0-9]+", "_", "".join(c for c in s if not unicodedata.combining(c))).strip("_")


def gravar(territorios, marco, valid, fonte, retificacoes_ate, coletado_em):
    """territorios: {codigo: (nome, slug)}; marco: {codigo: valores}; valid: {(codigo, comp): valores}."""
    (BASE / "estoque").mkdir(exist_ok=True)
    for codigo, (nome, s) in territorios.items():
        with (BASE / "estoque" / f"{codigo}_{s}.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["territorio", "grupamento", "estoque", "data_referencia", "retificacoes_ate", "fonte", "coletado_em"])
            for k, v in marco[codigo].items():
                w.writerow([codigo, k, v, DATA_REFERENCIA, retificacoes_ate, fonte, coletado_em])
        print(f"marco zero {codigo:>6} {nome:<26} ok")
    for codigo, (nome, _) in territorios.items():
        comps = sorted(c for t, c in valid if t == codigo)
        if not comps:
            print(f"validação {codigo:>6} {nome:<26} sem competências posteriores; arquivo mantido")
            continue
        with (BASE / "validacao" / f"{codigo}_estoque_painel.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["territorio", "grupamento", "competencia", "estoque", "retificacoes_ate", "coletado_em"])
            for comp in comps:
                for k, v in valid[(codigo, comp)].items():
                    w.writerow([codigo, k, comp, v, retificacoes_ate, coletado_em])
        print(f"validação {codigo:>6} {nome:<26} {len(comps)} competências ok")


def originais_manuais():
    """Os CSVs montados à mão a partir do painel; territórios fixos em TERRITORIOS."""
    marco = ler_painel(ler_csv(BASE / "Caged Mar 2020.csv"), lambda r: (r["regiao"], r["competencia"]))
    assert {r for r, _ in marco} == set(TERRITORIOS) and {c for _, c in marco} == {COMPETENCIA_MARCO}
    valid = ler_painel(ler_csv(BASE / "validacao" / "Caged Estoque 2020-2026 v2.csv"),
                       lambda r: (r["regiao"], r["competencia"]))
    assert {r for r, _ in valid} == set(TERRITORIOS)
    codigo = {nome: c for nome, (c, _) in TERRITORIOS.items()}
    gravar({c: (nome, s) for nome, (c, s) in TERRITORIOS.items()},
           {codigo[r]: v for (r, _), v in marco.items()},
           {(codigo[r], c): v for (r, c), v in valid.items()},
           FONTE, RETIFICACOES_ATE, COLETADO_EM)


def coleta(pasta):
    """Pasta `saida/marco-zero-*` do coletor: dados.csv (formato longo) + recorte.json."""
    pasta = Path(pasta).resolve()
    status = json.loads((pasta / "status.json").read_text(encoding="utf-8"))
    if status.get("status") != "concluido":
        raise SystemExit(f"{pasta}: status '{status.get('status')}', não 'concluido'. Coleta parcial não vira marco zero.")
    recorte = json.loads((pasta / "recorte.json").read_text(encoding="utf-8"))
    if "ultima_competencia_disponivel" not in recorte:
        raise SystemExit(f"{pasta}: recorte.json sem 'ultima_competencia_disponivel' (coletor antigo). "
                         "Sem ela não há retificacoes_ate; refaça a coleta.")
    retificacoes_ate = str(recorte["ultima_competencia_disponivel"])
    d = recorte["coleta_utc"][:8]
    coletado_em = f"{d[:4]}-{d[4:6]}-{d[6:]}"
    fonte = (
        "Painel Novo CAGED (MTE, Power BI), estoque ao fim de mar/2020 por grande grupamento, "
        f"coletado por marco-zero/coletor em {coletado_em} (modelo atualizado em "
        f"{recorte.get('atualizacao_modelo') or 'data não informada'}; última competência "
        f"{retificacoes_ate}). Metodologia do Novo CAGED. Ver marco-zero/FONTE.md"
    )
    linhas = ler_csv(pasta / "dados.csv")
    territorios = {}
    for r in linhas:
        territorios.setdefault(r["codigo_territorio"], (r["regiao"], slug(r["regiao"])))
    dados = ler_painel(linhas, lambda r: (r["codigo_territorio"], r["competencia"]))
    sem_marco = sorted(t for t in territorios if (t, COMPETENCIA_MARCO) not in dados)
    if sem_marco:
        raise SystemExit(f"Coleta sem a competência {COMPETENCIA_MARCO} para: {sem_marco}. "
                         "Inclua-a no período do config.json do coletor.")
    # Só competências posteriores ao marco servem de validação: antes dele o mart não tem estoque.
    gravar(territorios,
           {t: dados[(t, COMPETENCIA_MARCO)] for t in territorios},
           {k: v for k, v in dados.items() if k[1] > COMPETENCIA_MARCO},
           fonte, retificacoes_ate, coletado_em)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--coleta", help="pasta saida/marco-zero-* gerada por marco-zero/coletor")
    args = parser.parse_args()
    coleta(args.coleta) if args.coleta else originais_manuais()
