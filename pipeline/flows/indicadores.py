"""
Indicadores externos oficiais do boletim com IA (F19 parte 4), buscados por código, com os
números registrados em `numeros` como os demais fatos (o LLM não calcula nada).

- **Pix por município** (Banco Central, Olinda `Pix_DadosAbertos/TransacoesPixPorMunicipio`):
  o único dado de atividade econômica DO PRÓPRIO MUNICÍPIO, mensal e publicado antes do CAGED.
  Usados: empresas (PJ) que receberam Pix no mês (aproximação de empresas ativas) e o valor
  recebido por empresas (aproximação de faturamento). Cuidados, que vão para a nota:
  o Pix ainda cresce como meio de pagamento (parte da alta é adoção), por isso a leitura é
  RELATIVA (município × região × UF, variação em 12 meses); o município é o do cadastro da
  conta; valores nominais.
- **Selic** (SGS 432, meta ao ano): nacional; só entra quando Construção ou Comércio estão entre
  os destaques do mês (setores sensíveis a crédito; roteiro, seção 1.5). Dólar: fora, até o
  perfil de um município justificar.

Respostas guardadas em /data/ia/indicadores/ (reprodutibilidade: o mesmo mês dá o mesmo número
e o mesmo hash dos fatos). Falha de rede nunca derruba o boletim: o indicador fica ausente.
"""

import json
import os
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import fatos as fatos_mod
from fatos import Numeros, deslocar, pct, rotulo_competencia

PASTA = Path(os.environ.get("IA_DIR", "/data/ia")) / "indicadores"
URL_PIX = ("https://olinda.bcb.gov.br/olinda/servico/Pix_DadosAbertos/versao/v1/odata/"
           "TransacoesPixPorMunicipio(DataBase=@DataBase)")
URL_SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados"
SETORES_SENSIVEIS_A_CREDITO = {"Construção", "Comércio"}


def codigo_ibge(codigo6: str) -> int:
    """Código de 6 dígitos (CAGED) -> 7 dígitos do IBGE, com o dígito verificador
    (pesos 1,2,1,2,1,2; produto > 9 soma os algarismos). 280480 -> 2804805."""
    soma = 0
    for i, d in enumerate(codigo6):
        p = int(d) * (1 if i % 2 == 0 else 2)
        soma += p if p < 10 else p - 9
    return int(codigo6) * 10 + (10 - soma % 10) % 10


def _baixar_json(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": "boletim-caged"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def pix_da_uf(uf: int, competencia: int, baixar=_baixar_json, pasta: Path = PASTA) -> dict[int, dict]:
    """{código IBGE do município: linha do Pix} de uma UF numa competência, com cache em disco."""
    cache = pasta / f"pix_{uf}_{competencia}.json"
    if cache.exists():
        linhas = json.loads(cache.read_text(encoding="utf-8"))
    else:
        filtro = f"Estado_Ibge eq {uf} and AnoMes eq {competencia}"
        url = (f"{URL_PIX}?@DataBase='{competencia}'&$filter={urllib.parse.quote(filtro)}"
               "&$select=AnoMes,Municipio_Ibge,Municipio,QT_PES_RecebedorPJ,VL_RecebedorPJ&$format=json&$top=10000")
        linhas = baixar(url)["value"]
        if not linhas:
            return {}  # mês ainda não publicado: não guarda cache vazio
        pasta.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(linhas, ensure_ascii=False), encoding="utf-8")
    return {int(l["Municipio_Ibge"]): l for l in linhas}


def _soma(linhas: list[dict]) -> tuple[int, float]:
    return sum(l["QT_PES_RecebedorPJ"] for l in linhas), sum(l["VL_RecebedorPJ"] for l in linhas)


def bloco_pix(n: Numeros, fatos: dict, membros_regioes: dict[str, list[str]], baixar=_baixar_json,
              pasta: Path = PASTA) -> dict | None:
    comp = int(fatos["competencia"])
    territorio = fatos["territorio"]["codigo"]
    uf = int(territorio[:2])
    atual, antes = pix_da_uf(uf, comp, baixar, pasta), pix_da_uf(uf, deslocar(comp, -12), baixar, pasta)
    if not atual or not antes:
        return None
    recortes = [("territorio", fatos["territorio"]["nome"], [territorio])]
    recortes += [(f"regiao.{fatos_mod.chave(r)}", r, m) for r, m in membros_regioes.items()]
    recortes += [("uf", fatos["comparacao"]["uf"]["nome"] if fatos["comparacao"].get("uf") else "UF", None)]
    saida = {"fonte": "Banco Central, Pix por município (dados abertos)", "competencia": rotulo_competencia(comp),
             "comparado_com": rotulo_competencia(deslocar(comp, -12)), "recortes": []}
    variacoes = {}
    for chave_id, nome, codigos in recortes:
        if codigos is None:
            la, lb = list(atual.values()), list(antes.values())
        else:
            ibge = [codigo_ibge(c) for c in codigos]
            la, lb = [atual[c] for c in ibge if c in atual], [antes[c] for c in ibge if c in antes]
            if len(la) != len(ibge) or len(lb) != len(ibge):
                continue
        (emp, val), (emp_ant, val_ant) = _soma(la), _soma(lb)
        k = f"pix.{chave_id}"
        variacoes[chave_id] = pct(emp - emp_ant, emp_ant)
        saida["recortes"].append({
            "nome": nome,
            "empresas_recebedoras": n(f"{k}.empresas_recebedoras", emp, "empresas",
                                      f"empresas que receberam Pix em {nome} no mês"),
            "variacao_empresas_12m": n(f"{k}.variacao_empresas_12m", variacoes[chave_id], "pct",
                                       f"variação em 12 meses das empresas que receberam Pix em {nome}"),
            "valor_recebido_milhoes": n(f"{k}.valor_recebido_milhoes", round(val / 1e6, 1), "brl_milhoes",
                                        f"valor recebido via Pix por empresas de {nome}, em R$ milhões (nominal)"),
            "variacao_valor_12m": n(f"{k}.variacao_valor_12m", pct(val - val_ant, val_ant), "pct",
                                    f"variação nominal em 12 meses do valor recebido via Pix por empresas de {nome}"),
        })
    # Leitura relativa, por código: a adoção do Pix infla todas as variações por igual.
    if "territorio" in variacoes and "uf" in variacoes:
        saida["diferenca_empresas_vs_uf_pp"] = n(
            "pix.diferenca_empresas_vs_uf_pp", round(variacoes["territorio"] - variacoes["uf"], 2), "pp",
            "diferença, em pontos percentuais, entre o crescimento das empresas recebedoras de Pix no município e na UF")
    saida["cuidados"] = ("O Pix ainda cresce como meio de pagamento: parte da alta é adoção, por isso a leitura é "
                         "relativa (município contra região e estado). O município é o do cadastro da conta. "
                         "Valores nominais.")
    return saida


def bloco_selic(n: Numeros, fatos: dict, baixar=_baixar_json) -> dict | None:
    """Selic só com setor sensível a crédito entre os destaques."""
    if not SETORES_SENSIVEIS_A_CREDITO & set(fatos["setorial"]["destaques"]):
        return None
    comp = int(fatos["competencia"])
    ano, mes = divmod(comp, 100)
    fim = date(ano + (mes == 12), 1 if mes == 12 else mes + 1, 1) - timedelta(days=1)
    inicio = date(fim.year - 1, fim.month, 1)
    url = URL_SGS.format(serie=432) + f"?formato=json&dataInicial={inicio:%d/%m/%Y}&dataFinal={fim:%d/%m/%Y}"
    serie = baixar(url)
    if not serie:
        return None
    return {"fonte": "Banco Central, SGS 432 (meta Selic, % ao ano)",
            "fim_do_mes": n("selic.fim_do_mes", float(serie[-1]["valor"]), "pct", f"meta Selic em {rotulo_competencia(comp)}"),
            "doze_meses_antes": n("selic.doze_meses_antes", float(serie[0]["valor"]), "pct",
                                  f"meta Selic em {rotulo_competencia(deslocar(comp, -12))}"),
            "uso": "contexto para setores sensíveis a crédito em destaque; nunca explicação do saldo"}


def anexar(fatos: dict, warehouse: Path, baixar=_baixar_json, pasta: Path = PASTA) -> dict:
    """Acrescenta `indicadores_externos` aos fatos (e os números à tabela), recalculando o hash.
    Falha de rede ou dado ausente: o indicador fica de fora, com o motivo."""
    import duckdb
    n = Numeros()
    n.tabela = dict(fatos["numeros"])
    con = duckdb.connect(str(warehouse), read_only=True)
    try:
        linhas = con.execute("""select g.nome, r.territorio from regioes r join regioes g using (regiao)
                                where r.regiao in (select regiao from regioes where territorio = ?)""",
                             [fatos["territorio"]["codigo"]]).fetchall()
    finally:
        con.close()
    membros: dict[str, list[str]] = {}
    for nome, t in linhas:
        membros.setdefault(nome, [])
        if t not in membros[nome]:
            membros[nome].append(t)
    externos, ausentes = {}, {}
    for nome, funcao in (("pix", lambda: bloco_pix(n, fatos, membros, baixar, pasta)),
                         ("selic", lambda: bloco_selic(n, fatos, baixar))):
        try:
            bloco = funcao()
        except Exception as e:  # indicador externo nunca derruba o boletim
            ausentes[nome] = f"{type(e).__name__}: {e}"[:200]
            continue
        if bloco:
            externos[nome] = bloco
    fatos = {**fatos, "indicadores_externos": externos, "indicadores_ausentes": ausentes, "numeros": n.tabela}
    fatos.pop("hash", None)
    fatos["hash"] = fatos_mod.hash_dos_fatos(fatos)
    return fatos
