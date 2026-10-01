"""
Fatos do boletim com IA (F19 parte 1): tudo o que o boletim afirma, calculado por código.

Lê os marts (somente leitura) e monta, para um território e uma competência, um JSON com o
panorama, o desempenho setorial, os candidatos a desagregação, a comparação com a região e a
UF, o perfil das movimentações, o salário de admissão e os GATILHOS que selecionam os
destaques (docs/boletim-ia/roteiro.md, seções 1 e 3). Nenhum LLM entra aqui: os agentes da
F19 recebem este JSON pronto e só interpretam e redigem.

Cada número é registrado em `numeros` com um id estável (ex.: "panorama.saldo"): o
verificador da parte 3 confere que todo número do texto existe nesta tabela.

Limiares (base pequena, destaque, dominância de uma atividade...) vêm do perfil econômico do
município (perfis/<territorio>.toml, seção [limiares]); o que faltar usa LIMIARES_PADRAO.

Uso:
    python flows/fatos.py 280480 202607 [--warehouse /data/warehouse/caged.duckdb] [--saida fatos.json]
"""

import argparse
import hashlib
import json
import re
import tomllib
import unicodedata
from pathlib import Path

import duckdb

VERSAO = 2

LIMIARES_PADRAO = {
    # |saldo| mínimo (vínculos) para um grupamento ou atividade virar destaque
    "destaque_min_abs": 20,
    # quantos grupamentos destacar no máximo
    "top_grupamentos": 3,
    # uma atividade domina o grupamento se responde por esta fração das movimentações
    # (admissões + desligamentos) do grupamento nos últimos 12 meses (roteiro, seção 2)
    "participacao_dominante": 0.4,
    # desagregações sugeridas no máximo, somando todos os grupamentos
    "max_desagregacoes": 3,
    # admissões mínimas numa categoria do perfil (sexo, faixa) para ela ser interpretável
    "base_pequena_perfil": 30,
    # admissões com salário válido mínimas para interpretar o salário de admissão
    "base_pequena_salario": 30,
    # |saldo total| mínimo para calcular a contribuição de cada grupamento (roteiro, 1.2)
    "contribuicao_saldo_min": 20,
    # um grupamento concentra o resultado se tem esta fração da soma dos |saldos|
    "concentracao": 0.6,
    # anos anteriores mínimos do mesmo mês para classificar a sazonalidade
    "min_anos_sazonal": 3,
    # meses até uma competência deixar de ser provisória (var meses_para_consolidar do dbt)
    "meses_para_consolidar": 12,
    # mudança de participação nas admissões (pontos percentuais) que torna uma categoria do
    # perfil relevante, além de um saldo acima de destaque_min_abs
    "perfil_variacao_pp_relevante": 5.0,
}

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
         "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]

# Nomes curtos dos subgrupamentos (Tabela 1 do MTE) para a abertura do boletim; o nome oficial
# completo continua em `nome`. Escolhidos aqui, não pelo LLM, para serem os mesmos todo mês.
NOMES_CURTOS = {
    "Informação, comunicação e atividades financeiras, imobiliárias, profissionais e administrativas":
        "informação, comunicação, finanças e serviços profissionais e administrativos",
    "Administração pública, defesa, seguridade social, educação, saúde humana e serviços sociais":
        "administração pública, educação e saúde",
    "Comércio, reparação de veículos automotores e motocicletas": "comércio",
    "Transporte, armazenagem e correio": "transporte e armazenagem",
    "Alojamento e alimentação": "alojamento e alimentação",
    "Outros serviços": "outros serviços",
    "Serviços domésticos": "serviços domésticos",
    "Indústrias de Transformação": "indústria de transformação",
    "Indústria geral": "indústria extrativa, energia e saneamento",
}

PERFIS = Path(__file__).resolve().parent.parent / "perfis"


# --- utilidades ---------------------------------------------------------------------------

def deslocar(competencia: int, meses: int) -> int:
    """AAAAMM deslocado de `meses` (negativo = para trás)."""
    total = (competencia // 100) * 12 + (competencia % 100 - 1) + meses
    return (total // 12) * 100 + total % 12 + 1


def meses_entre(inicio: int, fim: int) -> int:
    return (fim // 100 - inicio // 100) * 12 + (fim % 100 - inicio % 100)


def chave(texto: str) -> str:
    """Trecho de id sem acento nem espaço: 'Não Identificado' -> 'nao_identificado'."""
    s = unicodedata.normalize("NFKD", texto.casefold())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def pct(numerador, denominador) -> float | None:
    """Percentual com duas casas; None se não houver base."""
    if numerador is None or not denominador:
        return None
    return round(100.0 * numerador / denominador, 2)


def rotulo_competencia(competencia: int) -> str:
    """202607 -> 'julho de 2026'."""
    return f"{MESES[competencia % 100 - 1]} de {competencia // 100}"


def carregar_limiares(territorio: str, pasta: Path = PERFIS) -> tuple[dict, dict]:
    """(limiares, perfil textual) do perfis/<territorio>.toml, com os padrões por baixo."""
    caminho = pasta / f"{territorio}.toml"
    dados = tomllib.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}
    desconhecidos = set(dados.get("limiares", {})) - set(LIMIARES_PADRAO)
    if desconhecidos:
        raise ValueError(f"{caminho}: limiares desconhecidos {sorted(desconhecidos)}")
    return {**LIMIARES_PADRAO, **dados.get("limiares", {})}, dados.get("perfil", {})


class Numeros:
    """Registro de todo número publicado, por id. É a tabela do verificador (parte 3)."""

    def __init__(self):
        self.tabela: dict[str, dict] = {}

    def __call__(self, id_: str, valor, unidade: str, descricao: str) -> dict:
        if id_ in self.tabela:
            raise ValueError(f"id repetido: {id_}")
        if isinstance(valor, float) and unidade == "vinculos":
            valor = int(valor)
        self.tabela[id_] = {"valor": valor, "unidade": unidade, "descricao": descricao}
        return {"id": id_, "valor": valor, "unidade": unidade}


def sazonalidade(valor, anteriores: dict[int, int], min_anos: int) -> dict:
    """Posição de `valor` na faixa mínimo–máximo do mesmo mês em anos anteriores (roteiro,
    seção 3.2). Com poucos anos não se usa desvio-padrão. `anos` diz o período da faixa, para
    o texto poder explicar o critério (revisão editorial, item 14)."""
    if len(anteriores) < min_anos or valor is None:
        return {"posicao": "historico_insuficiente", "anos": sorted(anteriores)}
    minimo, maximo = min(anteriores.values()), max(anteriores.values())
    posicao = "abaixo_da_faixa" if valor < minimo else "acima_da_faixa" if valor > maximo else "dentro_da_faixa"
    return {"posicao": posicao, "minimo": minimo, "maximo": maximo, "anos": sorted(anteriores)}


def _faixa(n, prefixo: str, saz: dict, alvo: str) -> dict:
    """Registra mínimo e máximo da faixa histórica, para poderem ser citados no texto."""
    if "minimo" not in saz:
        return saz
    periodo = f"{saz['anos'][0]} a {saz['anos'][-1]}"
    return {**saz,
            "minimo": n(f"{prefixo}.minimo", saz["minimo"], "vinculos", f"menor saldo de {alvo} no mesmo mês, {periodo}"),
            "maximo": n(f"{prefixo}.maximo", saz["maximo"], "vinculos", f"maior saldo de {alvo} no mesmo mês, {periodo}")}


# --- leitura --------------------------------------------------------------------------------

def _linhas(con, sql: str, params: list) -> list[dict]:
    cur = con.execute(sql, params)
    nomes = [d[0] for d in cur.description]
    return [dict(zip(nomes, r)) for r in cur.fetchall()]


def _serie_total(con, territorio: str) -> dict[int, dict]:
    """competência -> admissões, desligamentos, saldo do território (todos os grupamentos)."""
    return {r["competencia_mov"]: r for r in _linhas(
        con,
        "select competencia_mov, sum(admissoes) admissoes, sum(desligamentos) desligamentos, "
        "sum(saldo) saldo from mart_fluxo where territorio = ? group by 1",
        [territorio],
    )}


def _estoque_total(con, tabela: str, coluna: str, codigo: str, competencia: int) -> int | None:
    """Estoque somado dos grupamentos; None se algum grupamento não tiver estoque."""
    r = con.execute(
        f"select sum(estoque), count(estoque), count(*) from {tabela} "
        f"where {coluna} = ? and competencia_mov = ?",
        [codigo, competencia],
    ).fetchone()
    return int(r[0]) if r and r[2] and r[1] == r[2] else None


# --- montagem -------------------------------------------------------------------------------

def gerar_fatos(warehouse: Path, territorio: str, competencia: str | int,
                perfis: Path = PERFIS) -> dict:
    comp = int(competencia)
    limiares, perfil_textual = carregar_limiares(territorio, perfis)
    n = Numeros()
    con = duckdb.connect(str(warehouse), read_only=True)
    try:
        info = _linhas(con, "select territorio, nome, tipo from territorios where territorio = ?", [territorio])
        if not info:
            raise ValueError(f"Território {territorio} não está em territorios.csv.")
        info = info[0]
        ultima = con.execute("select max(competencia_mov) from mart_fluxo").fetchone()[0]
        serie = _serie_total(con, territorio)
        if comp not in serie:
            raise ValueError(f"Competência {comp} sem dados para o território {territorio}.")

        fatos = {
            "versao": VERSAO,
            "territorio": {"codigo": territorio, "nome": info["nome"], "tipo": info["tipo"]},
            "competencia": str(comp),
            # Rótulos para o texto: "julho de 2025" em vez de "o mesmo mês do ano anterior".
            "rotulos": {"competencia": rotulo_competencia(comp),
                        "ano_anterior": rotulo_competencia(deslocar(comp, -12)),
                        "mes_anterior": rotulo_competencia(deslocar(comp, -1))},
            "ultima_competencia_carregada": str(ultima),
            "provisorio": meses_entre(comp, ultima) < limiares["meses_para_consolidar"],
            "limiares": limiares,
            "perfil_economico": perfil_textual,
        }
        fatos["panorama"] = _panorama(con, n, territorio, comp, serie, limiares)
        fatos["setorial"] = _setorial(con, n, territorio, comp, fatos["panorama"], limiares)
        fatos["desagregacao"] = _desagregacao(con, n, territorio, comp, fatos["setorial"], limiares)
        fatos["comparacao"] = _comparacao(con, n, territorio, comp)
        fatos["perfil"] = _perfil(con, n, territorio, comp, limiares)
        fatos["salario"] = _salario(con, n, territorio, comp, limiares)
    finally:
        con.close()

    fatos["gatilhos"] = _gatilhos(fatos, limiares)
    fatos["numeros"] = n.tabela
    fatos["hash"] = hash_dos_fatos(fatos)
    return fatos


def hash_dos_fatos(fatos: dict) -> str:
    """Hash do conteúdo (sem o próprio campo `hash`): mesmos fatos, mesmo resultado reaproveitado."""
    return hashlib.sha256(json.dumps({k: v for k, v in fatos.items() if k != "hash"}, sort_keys=True,
                                     ensure_ascii=False, default=str).encode()).hexdigest()


def _panorama(con, n, territorio, comp, serie, lim) -> dict:
    atual = serie[comp]
    anterior_ano = serie.get(deslocar(comp, -12))
    p = {
        "saldo": n("panorama.saldo", atual["saldo"], "vinculos", "saldo do mês"),
        "admissoes": n("panorama.admissoes", atual["admissoes"], "vinculos", "admissões do mês"),
        "desligamentos": n("panorama.desligamentos", atual["desligamentos"], "vinculos", "desligamentos do mês"),
    }

    estoque = _estoque_total(con, "mart_estoque", "territorio", territorio, comp)
    estoque_ant = _estoque_total(con, "mart_estoque", "territorio", territorio, deslocar(comp, -1))
    estoque_12 = _estoque_total(con, "mart_estoque", "territorio", territorio, deslocar(comp, -12))
    if estoque is not None:
        p["estoque"] = n("panorama.estoque", estoque, "vinculos", "estoque ao fim do mês (estimativa a partir do estoque de referência do MTE)")
        p["taxa_mes"] = n("panorama.taxa_mes", pct(atual["saldo"], estoque_ant), "pct",
                          "variação do estoque no mês (saldo ÷ estoque do mês anterior)")
        p["taxa_12_meses"] = n("panorama.taxa_12_meses", pct(estoque - estoque_12, estoque_12) if estoque_12 else None,
                               "pct", "variação do estoque em 12 meses")

    if anterior_ano:
        p["mesmo_mes_ano_anterior"] = {
            "saldo": n("panorama.ano_anterior.saldo", anterior_ano["saldo"], "vinculos", "saldo do mesmo mês do ano anterior"),
            "admissoes": n("panorama.ano_anterior.admissoes", anterior_ano["admissoes"], "vinculos", "admissões do mesmo mês do ano anterior"),
            "desligamentos": n("panorama.ano_anterior.desligamentos", anterior_ano["desligamentos"], "vinculos", "desligamentos do mesmo mês do ano anterior"),
        }
        d_adm = atual["admissoes"] - anterior_ano["admissoes"]
        d_desl = atual["desligamentos"] - anterior_ano["desligamentos"]
        # Decomposição (roteiro 1.1): a variação do saldo = variação das admissões − variação
        # dos desligamentos. "motor" = o componente que mais contribuiu; "ambos" só quando os
        # dois empurram no mesmo sentido e o menor tem ao menos 1/3 do maior (senão, um −178
        # com um +8 viraria "ambos").
        contrib_adm, contrib_desl = d_adm, -d_desl
        maior, menor = sorted((abs(contrib_adm), abs(contrib_desl)), reverse=True)
        if (contrib_adm > 0) == (contrib_desl > 0) and contrib_adm and contrib_desl and menor >= maior / 3:
            motor = "ambos"
        else:
            motor = "admissoes" if abs(contrib_adm) >= abs(contrib_desl) else "desligamentos"
        p["decomposicao"] = {
            "variacao_saldo": n("panorama.decomposicao.variacao_saldo", d_adm - d_desl, "vinculos",
                                "variação do saldo frente ao mesmo mês do ano anterior"),
            "variacao_admissoes": n("panorama.decomposicao.variacao_admissoes", d_adm, "vinculos",
                                    "variação das admissões frente ao mesmo mês do ano anterior"),
            "variacao_desligamentos": n("panorama.decomposicao.variacao_desligamentos", d_desl, "vinculos",
                                        "variação dos desligamentos frente ao mesmo mês do ano anterior"),
            "motor": motor,
        }

    ano = comp // 100
    acum = [serie[c]["saldo"] for c in serie if c // 100 == ano and c <= comp]
    acum_ant = [serie[c]["saldo"] for c in serie if c // 100 == ano - 1 and c <= deslocar(comp, -12)]
    doze = [serie[c]["saldo"] for c in serie if deslocar(comp, -11) <= c <= comp]
    p["acumulado_ano"] = n("panorama.acumulado_ano", sum(acum), "vinculos", "saldo acumulado no ano até o mês")
    if acum_ant:
        p["acumulado_ano_anterior"] = n("panorama.acumulado_ano_anterior", sum(acum_ant), "vinculos",
                                        "saldo acumulado no mesmo período do ano anterior")
    if len(doze) == 12:
        p["acumulado_12_meses"] = n("panorama.acumulado_12_meses", sum(doze), "vinculos", "saldo acumulado em 12 meses")

    anteriores = {c // 100: serie[c]["saldo"] for c in serie if c % 100 == comp % 100 and c < comp}
    p["sazonalidade"] = _faixa(n, "panorama.faixa_historica",
                               sazonalidade(atual["saldo"], anteriores, lim["min_anos_sazonal"]), "todo o município")
    # Persistência (revisão editorial, item 20): o saldo dos dois meses anteriores.
    p["meses_anteriores"] = [
        {"competencia": rotulo_competencia(c),
         "saldo": n(f"panorama.saldo_{c}", serie[c]["saldo"], "vinculos", f"saldo de {rotulo_competencia(c)}")}
        for c in (deslocar(comp, -1), deslocar(comp, -2)) if c in serie
    ]
    return p


def _setorial(con, n, territorio, comp, panorama, lim) -> dict:
    grupos = {r["grupamento"]: r for r in _linhas(
        con,
        "select grupamento, sum(admissoes) admissoes, sum(desligamentos) desligamentos, sum(saldo) saldo "
        "from mart_fluxo where territorio = ? and competencia_mov = ? group by 1",
        [territorio, comp],
    )}
    estoques = {r["grupamento"]: r for r in _linhas(
        con,
        "select grupamento, estoque, taxa_variacao_mensal from mart_estoque "
        "where territorio = ? and competencia_mov = ?",
        [territorio, comp],
    )}
    historico = _linhas(
        con,
        "select grupamento, competencia_mov, sum(saldo) saldo from mart_fluxo "
        "where territorio = ? and competencia_mov % 100 = ? and competencia_mov <= ? group by 1, 2",
        [territorio, comp % 100, comp],
    )
    saldo_total = panorama["saldo"]["valor"]
    estoque_total = panorama.get("estoque", {}).get("valor")
    soma_abs = sum(abs(g["saldo"]) for g in grupos.values()) or None

    saida = {}
    for nome in sorted(set(grupos) | set(estoques)):
        g = grupos.get(nome, {"admissoes": 0, "desligamentos": 0, "saldo": 0})
        e = estoques.get(nome, {})
        k = f"setorial.{chave(nome)}"
        item = {
            "saldo": n(f"{k}.saldo", g["saldo"], "vinculos", f"saldo de {nome} no mês"),
            "admissoes": n(f"{k}.admissoes", g["admissoes"], "vinculos", f"admissões de {nome} no mês"),
            "desligamentos": n(f"{k}.desligamentos", g["desligamentos"], "vinculos", f"desligamentos de {nome} no mês"),
        }
        if e.get("estoque") is not None:
            item["estoque"] = n(f"{k}.estoque", e["estoque"], "vinculos", f"estoque de {nome} ao fim do mês")
            item["taxa_mes"] = n(f"{k}.taxa_mes",
                                 round(100.0 * e["taxa_variacao_mensal"], 2) if e["taxa_variacao_mensal"] is not None else None,
                                 "pct", f"variação do estoque de {nome} no mês")
            if estoque_total:
                item["participacao_estoque"] = n(f"{k}.participacao_estoque", pct(e["estoque"], estoque_total), "pct",
                                                 f"participação de {nome} no estoque do território")
        # `apoio`: números que servem ao CÓDIGO para escolher destaques, mas não entram no texto
        # (fora de `numeros`, o verificador os recusa). A contribuição percentual confunde o
        # leitor quando o saldo total é negativo ("108,43%"; revisão editorial, item 8).
        item["apoio"] = {}
        if abs(saldo_total) >= lim["contribuicao_saldo_min"]:
            item["apoio"]["contribuicao_saldo_pct"] = pct(g["saldo"], saldo_total)
        if soma_abs:
            item["apoio"]["participacao_movimento_liquido"] = round(abs(g["saldo"]) / soma_abs, 4)
        anteriores = {h["competencia_mov"] // 100: h["saldo"] for h in historico
                      if h["grupamento"] == nome and h["competencia_mov"] < comp}
        item["sazonalidade"] = sazonalidade(g["saldo"], anteriores, lim["min_anos_sazonal"])
        saida[nome] = item

    candidatos = [
        (nome, it) for nome, it in saida.items()
        if nome != "Não Identificado" and abs(it["saldo"]["valor"]) >= lim["destaque_min_abs"]
    ]
    candidatos.sort(key=lambda x: -abs(x[1]["saldo"]["valor"]))
    destaques = [nome for nome, _ in candidatos[: lim["top_grupamentos"]]]
    # Um grupamento fora da faixa sazonal também é destaque, mesmo fora do top.
    for nome, it in candidatos:
        if nome not in destaques and it["sazonalidade"]["posicao"] in ("abaixo_da_faixa", "acima_da_faixa"):
            destaques.append(nome)

    # Faixa histórica citável só para os destaques; nos demais fica só a posição.
    for nome, it in saida.items():
        if nome in destaques:
            it["sazonalidade"] = _faixa(n, f"setorial.{chave(nome)}.faixa_historica", it["sazonalidade"], nome)
        else:
            it["sazonalidade"] = {"posicao": it["sazonalidade"]["posicao"]}

    # Persistência dos destaques: saldo dos dois meses anteriores.
    anteriores = (deslocar(comp, -1), deslocar(comp, -2))
    for r in _linhas(con, "select grupamento, competencia_mov, sum(saldo) saldo from mart_fluxo "
                          "where territorio = ? and competencia_mov in (?, ?) group by 1, 2 order by 2 desc",
                     [territorio, *anteriores]):
        if r["grupamento"] in destaques:
            c = r["competencia_mov"]
            saida[r["grupamento"]].setdefault("meses_anteriores", []).append({
                "competencia": rotulo_competencia(c),
                "saldo": n(f"setorial.{chave(r['grupamento'])}.saldo_{c}", r["saldo"], "vinculos",
                           f"saldo de {r['grupamento']} em {rotulo_competencia(c)}")})

    resultado = {"grupamentos": saida, "destaques": destaques}
    # "Nos demais setores, saldo conjunto de +7" (revisão editorial, itens 6 e 8): por código.
    fora = [nome for nome in saida if nome not in destaques]
    if destaques and fora:
        resultado["fora_dos_destaques"] = {
            "grupamentos": [nome for nome in fora if nome != "Não Identificado"],
            "saldo": n("setorial.fora_dos_destaques.saldo",
                       sum(saida[nome]["saldo"]["valor"] for nome in fora), "vinculos",
                       "saldo conjunto dos grupamentos que não são destaque"),
        }
    return resultado


def _desagregacao(con, n, territorio, comp, setorial, lim) -> list[dict]:
    """Atividades dominantes dentro dos grupamentos em destaque (roteiro 1.2 e seção 2).

    Dominante = responde por `participacao_dominante` das movimentações do grupamento nos
    últimos 12 meses (aproximação do peso estrutural: não há estoque por atividade). Prefere
    o nível mais agregado: subgrupamento antes de divisão CNAE."""
    inicio = deslocar(comp, -11)
    sugestoes = []
    for grupamento in setorial["destaques"]:
        for nivel, coluna, rotulo in (("subgrupamento", "subgrupamento", "subgrupamento"),
                                      ("divisao_cnae", "divisao_cnae", "divisao_descricao")):
            linhas = _linhas(
                con,
                f"select {coluna} codigo, any_value({rotulo}) nome, "
                f"sum(admissoes + desligamentos) filter (where competencia_mov between ? and ?) mov_12, "
                f"sum(saldo) filter (where competencia_mov = ?) saldo, "
                f"sum(admissoes) filter (where competencia_mov = ?) admissoes, "
                f"sum(desligamentos) filter (where competencia_mov = ?) desligamentos, "
                f"sum(saldo) filter (where competencia_mov = ?) saldo_ano_anterior "
                f"from mart_fluxo where territorio = ? and grupamento = ? group by 1",
                [inicio, comp, comp, comp, comp, deslocar(comp, -12), territorio, grupamento],
            )
            total_12 = sum(r["mov_12"] or 0 for r in linhas)
            if len(linhas) < 2 or not total_12:
                continue  # grupamento com uma atividade só nesse nível: não há o que desagregar
            for r in sorted(linhas, key=lambda r: -(r["mov_12"] or 0)):
                part = (r["mov_12"] or 0) / total_12
                if part < lim["participacao_dominante"] or r["codigo"] in (None, "NI"):
                    continue
                k = f"desagregacao.{chave(grupamento)}.{nivel}.{chave(str(r['codigo']))}"
                saldo_grupamento = setorial["grupamentos"][grupamento]["saldo"]["valor"]
                # As divisões CNAE vêm do IBGE em maiúsculas ("CONSTRUÇÃO DE EDIFÍCIOS") e o redator
                # as copiava assim para o texto.
                nome = r["nome"].capitalize() if r["nome"] and r["nome"].isupper() else r["nome"]
                sugestoes.append({
                    "grupamento": grupamento,
                    "nivel": nivel,
                    "codigo": r["codigo"],
                    "nome": nome,
                    "nome_curto": NOMES_CURTOS.get(r["nome"], nome),
                    # só para escolher a atividade (revisão editorial, item 8): não vai ao texto
                    "apoio": {"participacao_movimentacoes_12m_pct": round(100.0 * part, 2)},
                    "saldo": n(f"{k}.saldo", r["saldo"] or 0, "vinculos", f"saldo de {nome} no mês"),
                    # "os demais subgrupamentos de Serviços somaram +46" (revisão, item 12)
                    "saldo_restante_do_grupamento": n(
                        f"{k}.saldo_restante", saldo_grupamento - (r["saldo"] or 0), "vinculos",
                        f"saldo do restante de {grupamento}, sem {nome}"),
                    "admissoes": n(f"{k}.admissoes", r["admissoes"] or 0, "vinculos", f"admissões de {nome} no mês"),
                    "desligamentos": n(f"{k}.desligamentos", r["desligamentos"] or 0, "vinculos", f"desligamentos de {nome} no mês"),
                    "saldo_ano_anterior": n(f"{k}.saldo_ano_anterior", r["saldo_ano_anterior"] or 0, "vinculos",
                                            f"saldo de {nome} no mesmo mês do ano anterior"),
                })
            if any(s["grupamento"] == grupamento for s in sugestoes):
                break  # achou no nível mais agregado: não desce para a divisão
    sugestoes.sort(key=lambda s: -abs(s["saldo"]["valor"]))
    return sugestoes[: lim["max_desagregacoes"]]


def _comparacao(con, n, territorio, comp) -> dict:
    """Município × região × UF (roteiro 1.3): taxas, com os valores absolutos ao lado."""
    def bloco(prefixo, nome, tabela, coluna, codigo):
        estoque = _estoque_total(con, tabela, coluna, codigo, comp)
        ant = _estoque_total(con, tabela, coluna, codigo, deslocar(comp, -1))
        doze = _estoque_total(con, tabela, coluna, codigo, deslocar(comp, -12))
        saldo = con.execute(f"select sum(saldo_consolidado) from {tabela} where {coluna} = ? and competencia_mov = ?",
                            [codigo, comp]).fetchone()[0]
        if estoque is None or saldo is None:
            return None
        return {
            "nome": nome,
            "saldo": n(f"{prefixo}.saldo", int(saldo), "vinculos", f"saldo de {nome} no mês"),
            "estoque": n(f"{prefixo}.estoque", estoque, "vinculos", f"estoque de {nome} ao fim do mês"),
            "taxa_mes": n(f"{prefixo}.taxa_mes", pct(saldo, ant), "pct", f"variação do estoque de {nome} no mês"),
            "taxa_12_meses": n(f"{prefixo}.taxa_12_meses", pct(estoque - doze, doze) if doze else None, "pct",
                               f"variação do estoque de {nome} em 12 meses"),
        }

    saida = {"territorio": None, "regioes": [], "uf": None}
    nome = con.execute("select nome from territorios where territorio = ?", [territorio]).fetchone()[0]
    saida["territorio"] = bloco("comparacao.territorio", nome, "mart_estoque", "territorio", territorio)
    for r in _linhas(con, "select distinct regiao, nome from regioes where territorio = ? order by 1", [territorio]):
        b = bloco(f"comparacao.regiao.{chave(r['regiao'])}", r["nome"], "mart_estoque_regiao", "regiao", r["regiao"])
        if b:
            saida["regioes"].append(b)
    uf = _linhas(con, "select territorio, nome from territorios where tipo = 'uf' and ativo and territorio = ?",
                 [territorio[:2]])
    if uf and uf[0]["territorio"] != territorio:
        saida["uf"] = bloco("comparacao.uf", uf[0]["nome"], "mart_estoque", "territorio", uf[0]["territorio"])
    saida["brasil"] = None  # não disponível nesta instalação (roteiro 1.3)
    return saida


def _perfil(con, n, territorio, comp, lim) -> dict:
    linhas = _linhas(
        con,
        "select competencia_mov, dimensao, categoria, admissoes, desligamentos, saldo "
        "from mart_perfil_movimentacoes where territorio = ? and competencia_mov in (?, ?) order by 2, 3",
        [territorio, comp, deslocar(comp, -12)],
    )
    saida = {}
    for dim in ("sexo", "faixa_etaria"):
        atual = [r for r in linhas if r["dimensao"] == dim and r["competencia_mov"] == comp]
        ant = {r["categoria"]: r for r in linhas if r["dimensao"] == dim and r["competencia_mov"] != comp}
        total_adm = sum(r["admissoes"] for r in atual)
        total_adm_ant = sum(r["admissoes"] for r in ant.values())
        cats = {}
        for r in atual:
            k = f"perfil.{dim}.{chave(r['categoria'])}"
            item = {
                "admissoes": n(f"{k}.admissoes", r["admissoes"], "vinculos", f"admissões ({r['categoria']}) no mês"),
                "desligamentos": n(f"{k}.desligamentos", r["desligamentos"], "vinculos", f"desligamentos ({r['categoria']}) no mês"),
                "saldo": n(f"{k}.saldo", r["saldo"], "vinculos", f"saldo ({r['categoria']}) no mês"),
                "participacao_admissoes": n(f"{k}.participacao_admissoes", pct(r["admissoes"], total_adm), "pct",
                                            f"participação de {r['categoria']} nas admissões do mês"),
                "base_pequena": r["admissoes"] < lim["base_pequena_perfil"],
            }
            a = ant.get(r["categoria"])
            variacao_pp = None
            if a and total_adm_ant:
                antes = pct(a["admissoes"], total_adm_ant)
                item["participacao_admissoes_ano_anterior"] = n(
                    f"{k}.participacao_admissoes_ano_anterior", antes, "pct",
                    f"participação de {r['categoria']} nas admissões do mesmo mês do ano anterior")
                variacao_pp = round(item["participacao_admissoes"]["valor"] - antes, 2)
                item["variacao_participacao_pp"] = n(
                    f"{k}.variacao_participacao_pp", variacao_pp, "pp",
                    f"variação da participação de {r['categoria']} nas admissões, em pontos percentuais")
            # Sem identificação vai para a nota metodológica, não para a análise (revisão, item 17).
            item["sem_identificacao"] = r["categoria"].startswith("Não identificad")
            # Só categorias relevantes são comentadas no texto (revisão, item 7).
            item["relevante"] = (not item["base_pequena"] and not item["sem_identificacao"] and (
                abs(r["saldo"]) >= lim["destaque_min_abs"]
                or (variacao_pp is not None and abs(variacao_pp) >= lim["perfil_variacao_pp_relevante"])))
            cats[r["categoria"]] = item
        saida[dim] = cats
    return saida


def _salario(con, n, territorio, comp, lim) -> dict | None:
    linhas = {r["competencia_mov"]: r for r in _linhas(
        con,
        "select competencia_mov, admissoes_com_salario_valido, salario_mediano_admissao, salario_medio_admissao "
        "from mart_salario_admissao where territorio = ? and competencia_mov in (?, ?)",
        [territorio, comp, deslocar(comp, -12)],
    )}
    atual = linhas.get(comp)
    if not atual:
        return None
    s = {
        "mediana": n("salario.mediana", float(atual["salario_mediano_admissao"]), "brl", "salário mediano de admissão (referência)"),
        "media": n("salario.media", float(atual["salario_medio_admissao"]), "brl", "salário médio de admissão (comparação)"),
        "base": n("salario.base", atual["admissoes_com_salario_valido"], "vinculos", "admissões com salário mensal válido"),
        "base_pequena": atual["admissoes_com_salario_valido"] < lim["base_pequena_salario"],
    }
    ant = linhas.get(deslocar(comp, -12))
    if ant:
        m, m_ant = float(atual["salario_mediano_admissao"]), float(ant["salario_mediano_admissao"])
        s["mediana_ano_anterior"] = n("salario.mediana_ano_anterior", m_ant, "brl",
                                      "salário mediano de admissão no mesmo mês do ano anterior (valor nominal)")
        s["variacao_nominal_mediana"] = n("salario.variacao_nominal_mediana", pct(m - m_ant, m_ant), "pct",
                                          "variação NOMINAL da mediana em 12 meses, sem correção pela inflação")
    return s


def _gatilhos(fatos: dict, lim: dict) -> list[dict]:
    """Os sinais que selecionam o que investigar (roteiro, seção 3). Cada gatilho aponta para
    ids de `numeros`; a IA não decide o que é atípico."""
    g = []
    if fatos["provisorio"]:
        g.append({"tipo": "provisorio", "detalhe": "competência ainda recebe declarações fora do prazo e exclusões"})
    saz = fatos["panorama"]["sazonalidade"]["posicao"]
    if saz in ("abaixo_da_faixa", "acima_da_faixa"):
        g.append({"tipo": "sazonal_total", "posicao": saz, "ids": ["panorama.saldo"]})
    for nome, it in fatos["setorial"]["grupamentos"].items():
        if nome in fatos["setorial"]["destaques"] and it["sazonalidade"]["posicao"] in ("abaixo_da_faixa", "acima_da_faixa"):
            g.append({"tipo": "sazonal_grupamento", "grupamento": nome, "posicao": it["sazonalidade"]["posicao"],
                      "ids": [it["saldo"]["id"]]})
        if it.get("apoio", {}).get("participacao_movimento_liquido", 0) >= lim["concentracao"] and abs(it["saldo"]["valor"]) >= lim["destaque_min_abs"]:
            g.append({"tipo": "concentracao", "grupamento": nome, "ids": [it["saldo"]["id"]]})
    for s in fatos["desagregacao"]:
        g.append({"tipo": "atividade_dominante", "grupamento": s["grupamento"], "nivel": s["nivel"],
                  "codigo": s["codigo"], "ids": [s["saldo"]["id"]]})
    pequenas = [f"{dim}:{cat}" for dim, cats in fatos["perfil"].items() for cat, it in cats.items() if it["base_pequena"]]
    if pequenas:
        g.append({"tipo": "base_pequena_perfil", "categorias": pequenas})
    if fatos["salario"] and fatos["salario"]["base_pequena"]:
        g.append({"tipo": "base_pequena_salario", "ids": ["salario.base"]})
    if abs(fatos["panorama"]["saldo"]["valor"]) < lim["contribuicao_saldo_min"]:
        g.append({"tipo": "saldo_total_perto_de_zero",
                  "detalhe": "contribuições por grupamento não calculadas", "ids": ["panorama.saldo"]})
    return g


def main():
    ap = argparse.ArgumentParser(description="Gera o JSON de fatos do boletim com IA (F19 parte 1).")
    ap.add_argument("territorio")
    ap.add_argument("competencia")
    ap.add_argument("--warehouse", default="/data/warehouse/caged.duckdb")
    ap.add_argument("--saida", help="arquivo JSON; padrão: saída padrão")
    a = ap.parse_args()
    fatos = gerar_fatos(Path(a.warehouse), a.territorio, a.competencia)
    texto = json.dumps(fatos, ensure_ascii=False, indent=2, default=str)
    if a.saida:
        Path(a.saida).write_text(texto + "\n", encoding="utf-8")
    else:
        print(texto)


if __name__ == "__main__":
    main()
