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
import html
import os
import json
import re
import time
import tomllib
import unicodedata
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import duckdb
from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext

import fatos as fatos_mod
import ia
from noticias import FONTES, Arquivo, _baixar, _permitido, carregar_fontes
from verificador import _NUMERO

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

# Conteúdo patrocinado nunca é evidência nem leitura (visto em 29/09/2026: matéria da Iguá em
# g1.globo.com/.../especial-publicitario/). Checado no link e no título, normalizados.
PATROCINADO = re.compile(r"especial[-_ ]publicitario|publieditorial|conteudo[-_ ]patrocinado|patrocinad|publicidade")

# Limiares iniciais, conservadores; calibrar com casos rotulados (parte 6).
# 0,7 na calibração de 29/09/2026 (19 notícias rotuladas, só 4 positivas: PROVISÓRIO; revisar
# os rótulos em perfis/calibracao_noticias.jsonl e recalibrar com mais casos).
LIMIAR_EMPREGO = 0.7
LIMIAR_HIPOTESE = 0.7
MAX_CANDIDATAS = {"competencia": 20, "recente": 15}
MAX_PARA_LER = 8          # notícias relevantes lidas pelo pesquisador por execução
TEXTO_MAX = 4_000         # caracteres do texto de cada notícia enviados ao pesquisador


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
        if PATROCINADO.search(normalizar(f"{n['link']} {n['titulo']}")):
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


# --- leitura do texto (código) --------------------------------------------------------------------

class _Paragrafos(HTMLParser):
    """Texto dos <p> de uma página, sem scripts. Suficiente para matérias jornalísticas."""

    def __init__(self):
        super().__init__()
        self.dentro, self.ignorar, self.atual, self.paragrafos = False, 0, [], []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.ignorar += 1
        elif tag == "p":
            self.dentro, self.atual = True, []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.ignorar = max(0, self.ignorar - 1)
        elif tag == "p" and self.dentro:
            texto = re.sub(r"\s+", " ", "".join(self.atual)).strip()
            if len(texto) >= 40:
                self.paragrafos.append(texto)
            self.dentro = False

    def handle_data(self, data):
        if self.dentro and not self.ignorar:
            self.atual.append(data)


def texto_da_noticia(n: dict, baixar=_baixar, dormir=time.sleep, ultimo_acesso: dict | None = None) -> str:
    """Texto da matéria (parágrafos), respeitando robots.txt e 2 s por host. Sem acesso,
    fica o resumo do feed. O texto é só lido, nunca republicado."""
    ultimo_acesso = ultimo_acesso if ultimo_acesso is not None else {}
    host = urlsplit(n["link"]).netloc
    espera = 2 - (time.monotonic() - ultimo_acesso.get(host, -1e9))
    if espera > 0:
        dormir(espera)
    try:
        if not _permitido(n["link"], baixar):
            return n.get("resumo", "")
        leitor = _Paragrafos()
        leitor.feed(html.unescape(baixar(n["link"]).decode("utf-8", "ignore")))
        texto = " ".join(leitor.paragrafos)
    except Exception:
        texto = ""
    finally:
        ultimo_acesso[host] = time.monotonic()
    return (texto or n.get("resumo", ""))[:TEXTO_MAX]


# --- pesquisador (LLM) e juiz de hipóteses (Jev) ---------------------------------------------------

class Evidencia(BaseModel):
    id: str = Field(description="id da notícia, como recebido")
    fato: str = Field(description="1 ou 2 frases, parafraseadas, só com o que o texto afirma")
    numeros: list[str] = Field(default_factory=list, description="números citados no fato, exatamente como no texto")
    territorio: str = Field(description="município, região ou estado de que o fato trata, segundo o texto")
    setor: str


class Pesquisa(BaseModel):
    evidencias: list[Evidencia] = Field(max_length=MAX_PARA_LER)


INSTRUCOES_PESQUISADOR = """Você lê notícias e extrai, de cada uma, o fato que pode afetar empregos com carteira assinada.
Regras:
- Use só o que o texto afirma. Não conclua nada sobre o CAGED nem sobre causas.
- 1 ou 2 frases por notícia, com suas palavras (não copie parágrafos).
- Número só se estiver no texto, escrito igual; liste-os em `numeros`.
- Nunca nomeie empresas pelo nome se a notícia não tratar de anúncio público da própria empresa.
- Se a notícia não traz fato relevante para o emprego, não gere evidência para ela.
"""


def criar_pesquisador(modelo) -> Agent:
    agente = Agent(modelo, output_type=Pesquisa, instructions=INSTRUCOES_PESQUISADOR, deps_type=dict, retries=1)

    @agente.output_validator
    def numeros_do_texto(ctx: RunContext[dict], saida: Pesquisa) -> Pesquisa:
        erros = []
        for e in saida.evidencias:
            fonte = ctx.deps.get(e.id)
            if fonte is None:
                erros.append(f"id {e.id} não existe")
                continue
            for m in _NUMERO.finditer(e.fato):
                if m.group().replace("−", "-").lstrip("-") not in fonte:
                    erros.append(f"{e.id}: número {m.group()} não está no texto da notícia")
        if erros and ctx.retry < ctx.max_retries:
            raise ModelRetry("Corrija: " + "; ".join(erros[:10]) + ". Use só números escritos no texto.")
        return saida

    return agente


def julgar_hipotese(ex: ia.Execucao, evidencia: dict, fatos: dict) -> float | None:
    """Probabilidade (Jev) de a evidência ser compatível, em período, setor e direção, com o
    movimento do CAGED no setor. Só para a janela da competência."""
    setor = evidencia["setor"] if evidencia["setor"] in fatos["setorial"]["grupamentos"] else None
    if not setor:
        return None
    g = fatos["setorial"]["grupamentos"][setor]
    estado = {"movimento_no_caged": {"setor": setor, "competencia": fatos["rotulos"]["competencia"],
                                     "saldo": g["saldo"]["valor"],
                                     "posicao_na_faixa_historica": g.get("sazonalidade", {}).get("posicao")},
              "evidencia": {"fato": evidencia["fato"], "data": evidencia["data"], "fonte": evidencia["fonte"]}}
    r = ex.decidir(estado, {"compativel": {
        "type": "noul",
        "instructions": "O fato da evidência aconteceu no período da competência, no mesmo setor, e tem a mesma "
                        "direção do saldo do CAGED (fato de contratação com saldo positivo, de demissão ou "
                        "fechamento com saldo negativo)?",
        "criteria": {"true": "Período, setor e direção compatíveis.",
                     "false": "Período, setor ou direção incompatíveis, ou o fato não afeta o número de vínculos."}}})
    return (r.get("compativel") or {}).get("noul")


def pesquisar(ex: ia.Execucao, agente: Agent, relevantes: list[dict], fatos: dict, baixar=_baixar,
              dormir=time.sleep) -> list[dict]:
    """Lê as notícias relevantes, extrai as evidências (pesquisador) e julga as da janela da
    competência como possível apoio a hipótese (Jev)."""
    lidas = sorted(relevantes, key=lambda n: (n["janela"] == "competencia", n["prioridade"]), reverse=True)[:MAX_PARA_LER]
    if not lidas:
        return []
    acessos: dict = {}
    textos = {n["id"]: texto_da_noticia(n, baixar, dormir, acessos) for n in lidas}
    entrada = [{"id": n["id"], "titulo": n["titulo"], "data": n["publicado_em"][:10],
                "fonte": n.get("veiculo") or n["fonte"], "texto": textos[n["id"]]} for n in lidas]
    pesquisa: Pesquisa = ex.rodar(agente, "pesquisador",
                                  "Notícias (JSON):\n" + json.dumps(entrada, ensure_ascii=False, indent=2), deps=textos)
    por_id = {n["id"]: n for n in lidas}
    saida = []
    for e in pesquisa.evidencias:
        n = por_id.get(e.id)
        if not n:
            continue
        ev = {**e.model_dump(), "titulo": n["titulo"], "link": n["link"], "fonte": n.get("veiculo") or n["fonte"],
              "data": n["publicado_em"][:10], "janela": n["janela"], "escala": n["escala"], "apoia_hipotese": False}
        if n["janela"] == "competencia":
            p = julgar_hipotese(ex, ev, fatos)
            ev["prob_compativel"] = p
            ev["apoia_hipotese"] = p is not None and p >= LIMIAR_HIPOTESE
        saida.append(ev)
    return saida


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

    juiz = next((m for m in cfg.modelos_permitidos if ia.e_modelo_de_decisao(m)), None)
    if not juiz:
        raise RuntimeError("Nenhum modelo de decisão (ex.: typesafe/jev-1.13) em IA_MODELOS_PERMITIDOS.")
    texto = [m for m in cfg.modelos_permitidos if not ia.e_modelo_de_decisao(m)]
    modelos = {"juiz": juiz, "pesquisador": os.environ.get("IA_MODELO_PESQUISADOR") or texto[-1]}
    kw = dict(execucao_kw or {})
    criar_modelo = kw.pop("criar_modelo", None) or (lambda papel: ia.modelo_openrouter(cfg, modelos[papel], papel))
    baixar, dormir = kw.pop("baixar", _baixar), kw.pop("dormir", time.sleep)
    post = kw.pop("post_decisoes", None)
    with ia.Execucao(cfg, modelos, territorio=fatos["territorio"]["codigo"], competencia=str(comp), **kw) as ex:
        if post:
            ex.post_decisoes = post
        triadas = triar(ex, candidatas, fatos)
        relevantes = [t for t in triadas if t["relevante"]]
        evid = pesquisar(ex, criar_pesquisador(criar_modelo("pesquisador")), relevantes, fatos, baixar, dormir)
    return {
        "competencia": str(comp),
        "gerado_em": gerado_em.isoformat(),
        "janelas": {k: [v[0].isoformat(), v[1].isoformat()] for k, v in js.items()},
        "noticias_no_periodo": len(noticias),
        "candidatas_por_codigo": len(candidatas),
        "limiar_emprego": LIMIAR_EMPREGO,
        "limiar_hipotese": LIMIAR_HIPOTESE,
        "triadas": triadas,
        "evidencias": evid,
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
                        "evidencias": [(e["janela"], e["data"], e["fato"][:120], e["apoia_hipotese"]) for e in r["evidencias"]],
                        "arquivo": str(destino)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
