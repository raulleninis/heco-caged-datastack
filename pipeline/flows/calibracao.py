"""
Calibração do Jev (F19 parte 6): mede, com casos de resposta conhecida, quão bem as
probabilidades do Jev separam o certo do errado, e escolhe o limiar pelo custo de cada erro
(o guia do Jev: "pick thresholds from the cost of each kind of mistake", ajustados em casos
rotulados).

Casos de AFIRMAÇÃO são gerados por código a partir dos fatos de várias competências, com a
verdade conhecida (sinal do saldo, posição na faixa histórica, comparação de taxas, direção das
admissões, participação no perfil), mais afirmações com CAUSA, que devem ser sempre recusadas.
Casos de TRIAGEM de notícias vêm de perfis/calibracao_noticias.jsonl, rotulados por pessoas.

Custo: deixar passar uma afirmação falsa (falso positivo) custa credibilidade; marcar uma
verdadeira como duvidosa (falso negativo) só custa tempo de revisão. Peso 3 contra 1.

Uso:
    python flows/calibracao.py 280480 202601..202607 [--warehouse ...]
Relatório em /data/ia/calibracao/.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import boletim_ia
import fatos as fatos_mod
import ia
from entrega import expandir_competencias

PESO_FALSO_POSITIVO = 3
PESO_FALSO_NEGATIVO = 1
LIMIARES = [round(0.1 * i, 1) for i in range(1, 10)]
CASOS_NOTICIAS = Path(__file__).resolve().parent.parent / "perfis" / "calibracao_noticias.jsonl"


def casos_de_afirmacao(f: dict) -> list[dict]:
    """(afirmação, ids, verdade) montados dos fatos; a verdade vem do próprio número."""
    rot = f["rotulos"]
    casos = []

    def caso(texto, ids, verdade, familia):
        casos.append({"texto": texto, "ids": ids, "verdade": verdade, "familia": familia, "competencia": f["competencia"]})

    for g, it in f["setorial"]["grupamentos"].items():
        s = it["saldo"]["valor"]
        if g == "Não Identificado" or s == 0:
            continue
        caso(f"O saldo de {g} foi positivo em {rot['competencia']}.", [it["saldo"]["id"]], s > 0, "sinal")
        caso(f"O saldo de {g} foi negativo em {rot['competencia']}.", [it["saldo"]["id"]], s < 0, "sinal")
    saz = f["panorama"]["sazonalidade"]
    if "minimo" in saz:
        ids = ["panorama.saldo", saz["minimo"]["id"], saz["maximo"]["id"]]
        for pos, frase in (("abaixo_da_faixa", "abaixo"), ("dentro_da_faixa", "dentro"), ("acima_da_faixa", "acima")):
            caso(f"O saldo do município ficou {frase} da faixa histórica de {rot['competencia'].split()[0]}.",
                 ids, saz["posicao"] == pos, "faixa")
    c = f["comparacao"]
    if c.get("territorio") and c.get("uf"):
        t, u = c["territorio"]["taxa_mes"], c["uf"]["taxa_mes"]
        if t["valor"] is not None and u["valor"] is not None and t["valor"] != u["valor"]:
            caso(f"A variação do estoque no mês foi maior no município do que em {c['uf']['nome']}.",
                 [t["id"], u["id"]], t["valor"] > u["valor"], "comparacao")
            caso(f"A variação do estoque no mês foi menor no município do que em {c['uf']['nome']}.",
                 [t["id"], u["id"]], t["valor"] < u["valor"], "comparacao")
    d = f["panorama"].get("decomposicao")
    if d and d["variacao_admissoes"]["valor"] != 0:
        # Duas formas de citar a mesma comparação: pela variação (−178) e pelos dois níveis
        # (1.060 antes, 882 agora). A calibração de 29/09/2026 mostrou que o Jev acerta uma e não a outra.
        niveis = ["panorama.admissoes", "panorama.ano_anterior.admissoes"]
        for ids, familia in (([d["variacao_admissoes"]["id"]], "direcao_por_variacao"), (niveis, "direcao_por_niveis")):
            caso(f"As admissões caíram em relação a {rot['ano_anterior']}.", ids, d["variacao_admissoes"]["valor"] < 0, familia)
            caso(f"As admissões cresceram em relação a {rot['ano_anterior']}.", ids, d["variacao_admissoes"]["valor"] > 0, familia)
    mulher = f["perfil"].get("sexo", {}).get("Mulher", {})
    if mulher.get("variacao_participacao_pp") and mulher["variacao_participacao_pp"]["valor"] != 0:
        v = mulher["variacao_participacao_pp"]
        caso("A participação das mulheres nas admissões aumentou.", [v["id"]], v["valor"] > 0, "perfil")
    # Causa: os fatos nunca sustentam; o Jev deve recusar sempre.
    for g in f["setorial"]["destaques"][:1]:
        it = f["setorial"]["grupamentos"][g]
        caso(f"O saldo de {g} mudou por causa do calendário eleitoral.", [it["saldo"]["id"]], False, "causa")
        caso(f"A mudança em {g} foi provocada pela política de juros.", [it["saldo"]["id"]], False, "causa")
    return casos


def metricas(casos: list[dict], chave_prob: str = "probabilidade") -> dict:
    """Por limiar: falsos positivos, falsos negativos, custo ponderado e acurácia."""
    validos = [c for c in casos if c.get(chave_prob) is not None]
    tabela = []
    for lim in LIMIARES:
        fp = sum(1 for c in validos if c[chave_prob] >= lim and not c["verdade"])
        fn = sum(1 for c in validos if c[chave_prob] < lim and c["verdade"])
        acertos = len(validos) - fp - fn
        tabela.append({"limiar": lim, "falsos_positivos": fp, "falsos_negativos": fn,
                       "custo": PESO_FALSO_POSITIVO * fp + PESO_FALSO_NEGATIVO * fn,
                       "acuracia": round(acertos / len(validos), 3) if validos else None})
    # Entre limiares empatados no menor custo, o do MEIO da faixa: tem margem dos dois lados
    # (o da ponta fica colado num caso observado e erra com o primeiro caso novo).
    empatados = [t for t in tabela if validos and t["custo"] == min(x["custo"] for x in tabela)]
    melhor = empatados[len(empatados) // 2] if empatados else None
    faixas = []
    for i in range(5):
        lo, hi = i / 5, (i + 1) / 5
        grupo = [c for c in validos if lo <= c[chave_prob] < hi or (i == 4 and c[chave_prob] == 1)]
        if grupo:
            faixas.append({"faixa": f"{lo:.1f}-{hi:.1f}", "casos": len(grupo),
                           "verdadeiros": round(sum(c["verdade"] for c in grupo) / len(grupo), 2)})
    return {"casos": len(validos), "por_limiar": tabela, "limiar_de_menor_custo": melhor, "confiabilidade": faixas}


def _execucao(cfg: ia.ConfigIA, juiz: str, territorio: str, rotulo: str, post_decisoes, **kw) -> ia.Execucao:
    ex = ia.Execucao(cfg, {"juiz": juiz}, territorio=territorio, competencia=rotulo, **kw)
    if post_decisoes:
        ex.post_decisoes = post_decisoes
    return ex


def rodar(warehouse: Path, territorio: str, competencias: list[str], cfg: ia.ConfigIA, post_decisoes=None,
          casos_noticias: Path = CASOS_NOTICIAS, **execucao_kw) -> dict:
    """Uma execução (com o teto de decisões dela) por competência, e uma para as notícias."""
    import evidencias as ev
    juiz = next(m for m in cfg.modelos_permitidos if ia.e_modelo_de_decisao(m))
    casos = []
    for comp in competencias:
        f = fatos_mod.gerar_fatos(warehouse, territorio, comp)
        da_comp = casos_de_afirmacao(f)
        with _execucao(cfg, juiz, territorio, f"calibracao {comp}", post_decisoes, **execucao_kw) as ex:
            for c in da_comp:
                b = boletim_ia.Boletim(titulo="", sintese="", panorama=[], setores=[], contexto_regional=[],
                                       perfil_e_remuneracao=[], pontos_de_atencao=[], nota_metodologica="",
                                       afirmacoes=[boletim_ia.Afirmacao(texto=c["texto"], ids=c["ids"])])
                c["probabilidade"] = boletim_ia.julgar_afirmacoes(ex, b, f)[0]["probabilidade"]
        casos += da_comp
    noticias = [json.loads(l) for l in casos_noticias.read_text(encoding="utf-8").splitlines() if l.strip()] \
        if casos_noticias.exists() else []
    if noticias:
        fatos_ref = fatos_mod.gerar_fatos(warehouse, territorio, competencias[-1])
        with _execucao(cfg, juiz, territorio, "calibracao noticias", post_decisoes, **execucao_kw) as ex:
            for n in noticias:
                r = ev.triar(ex, [{**n, "escala": n.get("escala", "estadual")}], fatos_ref)[0]
                n["probabilidade"] = (r["jev"].get("emprego") or {}).get("noul")
                n["territorio_jev"] = (r["jev"].get("territorio") or {}).get("choice")
                n["verdade"] = n["relevante"]
    por_familia = {}
    for c in casos:
        por_familia.setdefault(c["familia"], []).append(c)
    return {
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "competencias": competencias,
        "pesos": {"falso_positivo": PESO_FALSO_POSITIVO, "falso_negativo": PESO_FALSO_NEGATIVO},
        "afirmacoes": metricas(casos),
        "afirmacoes_por_familia": {
            k: {"casos": len(v), "acertos_no_limiar_atual": sum(
                1 for c in v if ((c["probabilidade"] or 0) >= boletim_ia.LIMIAR_AFIRMACAO) == c["verdade"])}
            for k, v in por_familia.items()},
        "noticias": metricas(noticias) if noticias else None,
        "erros_no_limiar_atual": [
            {k: c[k] for k in ("texto", "competencia", "familia", "verdade", "probabilidade")} for c in casos
            if ((c["probabilidade"] or 0) >= boletim_ia.LIMIAR_AFIRMACAO) != c["verdade"]],
        "casos": casos,
        "casos_noticias": noticias,
    }


def main():
    ap = argparse.ArgumentParser(description="Calibra os limiares do Jev com casos de resposta conhecida (F19 parte 6).")
    ap.add_argument("territorio")
    ap.add_argument("competencias", nargs="+", help="AAAAMM, AAAAMM..AAAAMM")
    ap.add_argument("--warehouse", default="/data/warehouse/caged.duckdb")
    a = ap.parse_args()
    cfg = ia.ConfigIA.do_ambiente()
    r = rodar(Path(a.warehouse), a.territorio, expandir_competencias(a.competencias), cfg)
    pasta = cfg.pasta / "calibracao"
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"calibracao_{a.territorio}_{r['gerado_em'][:10]}.json"
    destino.write_text(json.dumps(r, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    resumo = {"afirmacoes": {k: r["afirmacoes"][k] for k in ("casos", "limiar_de_menor_custo", "confiabilidade")},
              "afirmacoes_por_familia": r["afirmacoes_por_familia"],
              "noticias": {k: r["noticias"][k] for k in ("casos", "limiar_de_menor_custo")} if r["noticias"] else None,
              "erros_no_limiar_atual": r["erros_no_limiar_atual"], "arquivo": str(destino)}
    print(json.dumps(resumo, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
