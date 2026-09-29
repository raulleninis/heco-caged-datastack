"""
Evidências externas do boletim com IA (F19 parte 4): seleção por código e triagem pelo Jev das
notícias acumuladas pelo coletor diário (flows/noticias.py).

Janelas (decisão de 29/09/2026; o CAGED sai com ~1 mês de defasagem):
- "competencia": do 1º dia do mês ANTERIOR à competência até 15 dias depois do fim dela. Só
  notícias desta janela podem sustentar uma hipótese sobre o mês (alternativa 1).
- "recente": os 30 dias antes da geração do boletim. Servem só como sinal para acompanhar nos
  próximos meses, nunca como explicação do mês passado (alternativa 2).
- qualquer notícia selecionada pode entrar em "leituras relacionadas", sem afirmação (alternativa 3).
Uma notícia nas duas janelas conta como da competência.

Seleção por código (barata, antes de qualquer modelo):
- território: nome do município, dos membros das suas regiões e da UF (do warehouse), mais os
  termos extras de perfis/<territorio>.toml ([evidencias] termos_territorio);
- tema: palavras de emprego e de cada grupamento; notícia nacional só passa se tocar um setor
  em destaque no mês ou falar de emprego;
- `excluir_links` de cada fonte (o feed do Sebrae SE mistura conteúdo de outros estados).

Triagem pelo Jev (papel "juiz" da Execucao, com o teto de decisões): território, relação com o
emprego formal e setor, com probabilidades. As probabilidades e os limiares ficam gravados para
calibração (o próprio guia do Jev recomenda ajustar limiares com casos rotulados).

Uso:
    python flows/evidencias.py 280480 202607 [--gerado-em 2026-09-29] [--warehouse ...]
"""

import argparse
import json
import re
import tomllib
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb

import fatos as fatos_mod
import ia
from noticias import FONTES, Arquivo, carregar_fontes

PERFIS = Path(__file__).resolve().parent.parent / "perfis"

PALAVRAS_EMPREGO = [
    "emprego", "empregos", "vagas", "contrata", "demiss", "demite", "desemprego", "caged",
    "trabalhador", "carteira assinada", "postos de trabalho", "mao de obra", "admiss", "desligament",
    "abertura de empresas", "fechamento", "encerra", "investimento", "expansao", "greve",
]
PALAVRAS_SETOR = {
    "Serviços": ["servico", "call center", "teleatendimento", "telemarketing", "tecnologia", "banco", "financeir",
                 "saude", "hospital", "educacao", "escola", "transporte", "logistica", "turismo", "hotel",
                 "restaurante", "alimentacao", "administracao publica", "prefeitura", "terceirizad"],
    "Comércio": ["comercio", "varejo", "loja", "lojas", "shopping", "vendas", "supermercado", "atacad", "lojista"],
    "Indústria": ["industria", "fabrica", "industrial", "petroleo", "fertilizante", "cimento",
                  "textil", "calcad", "manufatura", "gas natural"],
    "Construção": ["construcao", "obra", "obras", "imobiliari", "habitacao", "moradia", "pavimentacao",
                   "infraestrutura", "canteiro"],
    "Agropecuária": ["agro", "safra", "colheita", "rural", "pecuaria", "agricult", "citros", "laranja", "milho",
                     "cana-de-acucar", "cana de acucar"],
}

# Limiares iniciais, conservadores; calibrar com casos rotulados (parte 6).
LIMIAR_EMPREGO = 0.6
MAX_CANDIDATAS = {"competencia": 20, "recente": 15}


def normalizar(texto: str) -> str:
    s = unicodedata.normalize("NFKD", (texto or "").casefold())
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c)))


def janelas(competencia: int, gerado_em: date) -> dict[str, tuple[date, date]]:
    ano, mes = divmod(competencia, 100)
    anterior = date(ano - (mes == 1), 12 if mes == 1 else mes - 1, 1)
    fim_mes = (date(ano + (mes == 12), 1 if mes == 12 else mes + 1, 1) - timedelta(days=1))
    return {"competencia": (anterior, fim_mes + timedelta(days=15)),
            "recente": (gerado_em - timedelta(days=30), gerado_em)}


def meses_entre(inicio: date, fim: date) -> list[str]:
    """'AAAA-MM' de todos os meses de inicio a fim (os arquivos do coletor são mensais)."""
    meses, a, m = [], inicio.year, inicio.month
    while (a, m) <= (fim.year, fim.month):
        meses.append(f"{a:04d}-{m:02d}")
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    return meses


def janela_da(publicado_em: str | None, js: dict) -> str | None:
    if not publicado_em:
        return None
    d = datetime.fromisoformat(publicado_em).date()
    for nome in ("competencia", "recente"):
        inicio, fim = js[nome]
        if inicio <= d <= fim:
            return nome
    return None


def termos_territoriais(warehouse: Path, territorio: str, extras=()) -> list[str]:
    """Nome do território, dos municípios das suas regiões e da UF, normalizados."""
    con = duckdb.connect(str(warehouse), read_only=True)
    try:
        nomes = [r[0] for r in con.execute(
            """select nome from territorios where territorio = ?
               union select t.nome from regioes r join territorios t using (territorio)
                     where r.regiao in (select regiao from regioes where territorio = ?)
               union select nome from territorios where tipo = 'uf' and territorio = ?""",
            [territorio, territorio, territorio[:2]]).fetchall()]
    finally:
        con.close()
    return sorted({normalizar(t) for t in [*nomes, *extras] if t})


def _contem(texto: str, termos) -> list[str]:
    return [t for t in termos if re.search(rf"\b{re.escape(t)}", texto)]


def selecionar(noticias: list[dict], js: dict, termos: list[str], destaques: list[str],
               exclusoes: dict[str, str]) -> list[dict]:
    """Candidatas por código, com janela, território, setores e uma nota de prioridade."""
    saida = []
    for n in noticias:
        janela = janela_da(n.get("publicado_em"), js)
        if not janela:
            continue
        padrao = exclusoes.get(n["fonte"])
        if padrao and re.search(padrao, n["link"]):
            continue
        texto = normalizar(f"{n['titulo']} {n.get('resumo', '')}")
        territorio = _contem(texto, termos)
        setores = [g for g, palavras in PALAVRAS_SETOR.items() if _contem(texto, palavras)]
        emprego = bool(_contem(texto, PALAVRAS_EMPREGO))
        nos_destaques = [s for s in setores if s in destaques]
        if not (setores or emprego):
            continue
        if not territorio and not (n["escala"] == "nacional" and (nos_destaques or emprego)):
            continue
        saida.append({**n, "janela": janela, "termos_territorio": territorio, "setores": setores,
                      "fala_de_emprego": emprego,
                      "prioridade": 2 * bool(territorio) + 2 * len(nos_destaques) + emprego})
    escolhidas = []
    for nome, maximo in MAX_CANDIDATAS.items():
        da_janela = sorted((s for s in saida if s["janela"] == nome),
                           key=lambda s: (s["prioridade"], s["publicado_em"]), reverse=True)
        escolhidas += da_janela[:maximo]
    return escolhidas


def perguntas_triagem(fatos: dict) -> dict:
    c = fatos["comparacao"]
    municipio = fatos["territorio"]["nome"]
    regiao = c["regioes"][0]["nome"] if c.get("regioes") else "região"
    uf = c["uf"]["nome"] if c.get("uf") else "o estado"
    return {
        "territorio": {
            "type": "choice", "instructions": "De que território a notícia trata?",
            "criteria": {"municipio_ou_regiao": f"Trata de {municipio} ou de outro município da {regiao}.",
                         "estado": f"Trata de {uf} de modo geral, sem município específico da {regiao}.",
                         "outro": f"Trata de outro estado ou município fora de {uf}, ou do Brasil sem menção a {uf}."}},
        "emprego": {
            "type": "noul",
            # O CAGED só conta vínculos CLT: servidor estatutário (professor da rede pública, por
            # exemplo) não entra, e o Jev não sabe disso sem o critério (visto em 29/09/2026).
            "instructions": "A notícia relata um fato que pode alterar o número de empregos com carteira assinada "
                            "(CLT): contratações, demissões, abertura ou fechamento de empresas, obras, "
                            "investimentos, crise ou expansão de um setor?",
            "criteria": {"true": "Relata um fato com efeito plausível sobre empregos com carteira assinada, em "
                                 "empresas privadas, estatais ou terceirizadas.",
                         "false": "Não afeta empregos com carteira assinada: servidores públicos estatutários "
                                  "(professores e servidores das redes públicas, concursos para cargos efetivos), "
                                  "cursos, golpes, eleições, serviços ao consumidor, cotações, entretenimento."}},
        "setor": {
            "type": "choice", "instructions": "Qual grande setor econômico o fato afeta mais diretamente?",
            "criteria": {"Serviços": "Serviços, inclusive administração pública, saúde, educação, transporte e finanças.",
                         "Comércio": "Comércio varejista ou atacadista.",
                         "Indústria": "Indústria, inclusive extrativa, petróleo e gás, energia e saneamento.",
                         "Construção": "Construção civil e obras.",
                         "Agropecuária": "Agricultura, pecuária e pesca.",
                         "nenhum": "Nenhum setor específico."}},
    }


def triar(ex: ia.Execucao, candidatas: list[dict], fatos: dict) -> list[dict]:
    """Uma decisão do Jev por notícia. Relevante = provável efeito sobre o emprego formal e
    território do estado (notícia nacional dispensa o território)."""
    perguntas = perguntas_triagem(fatos)
    triadas = []
    for n in candidatas:
        estado = {"noticia": {"titulo": n["titulo"], "resumo": n.get("resumo", ""), "fonte": n.get("veiculo") or n["fonte"],
                              "data": n["publicado_em"][:10]},
                  "setores_em_destaque_no_mes": fatos["setorial"]["destaques"]}
        r = ex.decidir(estado, perguntas)
        p_emprego = (r.get("emprego") or {}).get("noul")
        terr = (r.get("territorio") or {}).get("choice")
        relevante = (p_emprego is not None and p_emprego >= LIMIAR_EMPREGO
                     and (terr in ("municipio_ou_regiao", "estado") or n["escala"] == "nacional"))
        triadas.append({**n, "jev": r, "relevante": relevante})
    return triadas


def gerar_evidencias(fatos: dict, warehouse: Path, cfg: ia.ConfigIA, gerado_em: date, *,
                     arquivo: Arquivo | None = None, execucao_kw: dict | None = None,
                     fontes: list[dict] | None = None, perfis: Path = PERFIS) -> dict:
    comp = int(fatos["competencia"])
    js = janelas(comp, gerado_em)
    arquivo = arquivo or Arquivo()
    meses = meses_entre(min(i for i, _ in js.values()), max(f for _, f in js.values()))
    noticias = [n for m in meses for n in arquivo.ler(m)]
    perfil = perfis / f"{fatos['territorio']['codigo']}.toml"
    extras = tomllib.loads(perfil.read_text(encoding="utf-8")).get("evidencias", {}).get("termos_territorio", []) \
        if perfil.exists() else []
    termos = termos_territoriais(warehouse, fatos["territorio"]["codigo"], extras)
    fontes = fontes if fontes is not None else carregar_fontes(FONTES)
    exclusoes = {f["nome"]: f["excluir_links"] for f in fontes if f.get("excluir_links")}
    candidatas = selecionar(noticias, js, termos, fatos["setorial"]["destaques"], exclusoes)

    modelos = {"juiz": next(m for m in cfg.modelos_permitidos if m.startswith("typesafe/"))}
    with ia.Execucao(cfg, modelos, territorio=fatos["territorio"]["codigo"], competencia=str(comp),
                     **(execucao_kw or {})) as ex:
        triadas = triar(ex, candidatas, fatos)
    return {
        "competencia": str(comp),
        "gerado_em": gerado_em.isoformat(),
        "janelas": {k: [v[0].isoformat(), v[1].isoformat()] for k, v in js.items()},
        "noticias_no_periodo": len(noticias),
        "candidatas_por_codigo": len(candidatas),
        "limiar_emprego": LIMIAR_EMPREGO,
        "triadas": triadas,
    }


def main():
    ap = argparse.ArgumentParser(description="Seleciona e tria as notícias de uma competência (F19 parte 4).")
    ap.add_argument("territorio")
    ap.add_argument("competencia")
    ap.add_argument("--gerado-em", default=datetime.now(timezone.utc).date().isoformat())
    ap.add_argument("--warehouse", default="/data/warehouse/caged.duckdb")
    a = ap.parse_args()
    cfg = ia.ConfigIA.do_ambiente()
    f = fatos_mod.gerar_fatos(Path(a.warehouse), a.territorio, a.competencia)
    r = gerar_evidencias(f, Path(a.warehouse), cfg, date.fromisoformat(a.gerado_em))
    pasta = cfg.pasta / "evidencias"
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"{a.territorio}_{a.competencia}_{a.gerado_em}.json"
    destino.write_text(json.dumps(r, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: r[k] for k in ("janelas", "noticias_no_periodo", "candidatas_por_codigo")}
                     | {"relevantes": [(t["janela"], t["publicado_em"][:10], t["titulo"][:80]) for t in r["triadas"] if t["relevante"]],
                        "arquivo": str(destino)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
