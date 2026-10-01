"""
Projeção do emprego formal para a seção "Perspectivas" do boletim com IA (F21).

Implementa docs/boletim-ia/especificacao-projecao.md. As funções de cálculo (reconstruir_estoque,
metodo_taxas, metodo_ets, metodo_ingenuo, projetar, trajetoria_estoque, backtest) são as da
implementação de referência (projecao_caged.py), sem mudança de método nem de parâmetro: o teste
de aceitação da seção 11 da especificação é reproduzido (docs/boletim-ia/projecao.md).

Resumo do método:
  1. Taxas sazonais: taxa = fluxo_t / estoque_{t-1}; projeção = média da taxa do mesmo mês nos 3
     últimos anos disponíveis (sem 2020) × estoque projetado.
  2. ETS (Holt-Winters): log(fluxo), tendência aditiva amortecida, sazonalidade aditiva (12),
     dados desde 2021-01.
  3. Combinação: média simples de (1) e (2), separada para admissões e desligamentos. Saldo e
     estoque saem SEMPRE pela identidade contábil.
  4. Faixa provável: percentis 10% e 90% dos erros de estoque no backtest de origem móvel, por
     horizonte.

O que muda em relação à referência, por causa do projeto:
- O estoque âncora é o da página 1 do boletim (fatos["panorama"]["estoque"], do mart_estoque).
- As edições ficam num DuckDB próprio por território (/data/ia/projecoes/<territorio>.duckdb, a
  mesma tabela `projecao_edicoes` da especificação), não no warehouse: o boletim com IA lê o
  warehouse só para leitura e o flow diário é o único escritor dele. Grava-se ao PUBLICAR
  (entrega_ia.py enviar), não ao gerar: uma edição testada e não enviada não vira "edição anterior".
- Os textos são os modelos fixos da especificação, gerados por código; o LLM não escreve sobre a
  projeção (o bloco fica fora do prompt).
- Validação que bloqueia (seção 10) -> ProjecaoBloqueada: a seção sai do boletim e o motivo vai
  para o relatório de revisão. Avisos vão para o relatório de revisão.

Manual (teste de aceitação ou conferência):
  python flows/projecao.py WAREHOUSE --estoque 25364 [--complemento '{"2026-08":[1028,1107]}'] [--edicoes PASTA]
"""
from __future__ import annotations

import json
import os
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

MESES_EXT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
             "setembro", "outubro", "novembro", "dezembro"]
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
PASTA = Path(os.environ.get("IA_DIR", "/data/ia")) / "projecoes"

AVISO_EXPERIMENTAL = ("Projeção experimental: leia com cautela. Os valores podem mudar tanto pela evolução "
                      "real do emprego quanto por ajustes e refinamentos na metodologia de previsão.")


class ProjecaoBloqueada(RuntimeError):
    """Validação da seção 10 da especificação que bloqueia a publicação da projeção."""


# --------------------------------------------------------------------------- #
# Configuração (parâmetros da especificação; revisão anual, nunca mensal)
# --------------------------------------------------------------------------- #
@dataclass
class Config:
    anos_excluidos_taxas: tuple[int, ...] = (2020,)   # pandemia
    n_anos_taxas: int = 3                              # média do mesmo mês nos N últimos anos
    ets_inicio: str = "2021-01"                        # início da amostra do ETS
    backtest_primeira_origem: str = "2022-12"          # 1ª origem do backtest (ETS precisa de 24 meses)
    quantis: tuple[float, float] = (0.10, 0.90)        # faixa provável (80%)
    min_obs_quantil: int = 8                           # mínimo de erros por horizonte p/ usar o quantil
    janela_grafico_inicio_anos_atras: int = 1          # gráfico começa em jan do ano anterior
    tabela_edicoes: str = "projecao_edicoes"           # onde as edições ficam guardadas
    extras: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# 1. Dados
# --------------------------------------------------------------------------- #
def carregar_fluxos(warehouse: str | Path, complemento: dict | None = None) -> pd.DataFrame:
    """Admissões (A) e desligamentos (D) mensais do município do boletim, do
    mart_caged_reconciliado (consolidado + provisório, somando grupamentos). `complemento`
    ({"AAAA-MM": (A, D)}) só para o teste de aceitação; em produção fica vazio."""
    con = duckdb.connect(str(warehouse), read_only=True)
    try:
        linhas = con.execute(
            """
            select competencia_mov as p,
                   sum(admissoes_consolidadas)     as A,
                   sum(desligamentos_consolidados) as D
            from mart_caged_reconciliado
            group by 1 order by 1
            """
        ).fetchall()
    finally:
        con.close()
    df = pd.DataFrame(linhas, columns=["p", "A", "D"])
    df["date"] = pd.to_datetime(df.p.astype(int).astype(str), format="%Y%m")
    df = df.set_index("date")[["A", "D"]].astype(float)
    for k, (a, d) in (complemento or {}).items():
        df.loc[pd.Timestamp(k + "-01")] = [float(a), float(d)]
    df = df.sort_index()
    esperado = pd.date_range(df.index.min(), df.index.max(), freq="MS")
    faltando = esperado.difference(df.index)
    if len(faltando):
        raise ProjecaoBloqueada(f"Meses ausentes na série: {[d.strftime('%Y-%m') for d in faltando]}")
    df["saldo"] = df.A - df.D
    return df


def reconstruir_estoque(df: pd.DataFrame, estoque_ancora: float) -> pd.DataFrame:
    """Estoque do último mês = âncora (o mesmo número publicado no boletim); meses anteriores
    recuados pela identidade S_{t-1} = S_t - saldo_t."""
    df = df.copy()
    s = np.empty(len(df))
    s[-1] = estoque_ancora
    for i in range(len(df) - 2, -1, -1):
        s[i] = s[i + 1] - df.saldo.iloc[i + 1]
    df["S"] = s
    return df


# --------------------------------------------------------------------------- #
# 2. Métodos (todos recebem a origem T e o horizonte H; usam só dados <= T)
# --------------------------------------------------------------------------- #
def _meses_a_frente(T: pd.Timestamp, H: int) -> pd.DatetimeIndex:
    return pd.date_range(T + pd.DateOffset(months=1), periods=H, freq="MS")


def metodo_taxas(df: pd.DataFrame, T: pd.Timestamp, H: int, cfg: Config) -> np.ndarray:
    h = df.loc[:T]
    s_prev = h.S.shift(1)
    ta, td = h.A / s_prev, h.D / s_prev
    ok = ~ta.index.year.isin(cfg.anos_excluidos_taxas)
    s = h.S.iloc[-1]
    out = []
    for d in _meses_a_frente(T, H):
        m = d.month
        ra = ta[ok & (ta.index.month == m)].dropna().iloc[-cfg.n_anos_taxas:].mean()
        rd = td[ok & (td.index.month == m)].dropna().iloc[-cfg.n_anos_taxas:].mean()
        a, dd = ra * s, rd * s
        s = s + a - dd                      # o estoque projetado alimenta o mês seguinte
        out.append((a, dd))
    return np.array(out)


def metodo_ets(df: pd.DataFrame, T: pd.Timestamp, H: int, cfg: Config) -> np.ndarray:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    h = df.loc[cfg.ets_inicio:T]
    cols = []
    for c in ("A", "D"):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # avisos de convergência do otimizador: só ruído aqui
            mod = ExponentialSmoothing(
                np.log(h[c].values), trend="add", damped_trend=True,
                seasonal="add", seasonal_periods=12,
            ).fit(optimized=True)
        cols.append(np.exp(mod.forecast(H)))
    return np.column_stack(cols)


def metodo_ingenuo(df: pd.DataFrame, T: pd.Timestamp, H: int, cfg: Config) -> np.ndarray:
    """Referência: repete o mesmo mês do último ano observado. Não é publicado."""
    h = df.loc[:T]
    out = []
    for k, d in enumerate(_meses_a_frente(T, H), 1):
        b = d - pd.DateOffset(months=12 * ((k - 1) // 12 + 1))
        out.append((h.A.loc[b], h.D.loc[b]))
    return np.array(out)


def projetar(df: pd.DataFrame, T: pd.Timestamp, H: int, cfg: Config) -> dict[str, np.ndarray]:
    r = {
        "taxas": metodo_taxas(df, T, H, cfg),
        "ets": metodo_ets(df, T, H, cfg),
        "ingenuo": metodo_ingenuo(df, T, H, cfg),
    }
    r["comb"] = (r["taxas"] + r["ets"]) / 2
    return r


def trajetoria_estoque(s0: float, fluxos: np.ndarray) -> np.ndarray:
    return s0 + np.cumsum(fluxos[:, 0] - fluxos[:, 1])


# --------------------------------------------------------------------------- #
# 3. Backtest (origem móvel) -> faixas e métricas
# --------------------------------------------------------------------------- #
def backtest(df: pd.DataFrame, H: int, cfg: Config) -> dict:
    T_fim = df.index[-1]
    origens = pd.date_range(cfg.backtest_primeira_origem, T_fim - pd.DateOffset(months=1), freq="MS")
    erros_S = {k: [] for k in range(1, H + 1)}
    mae = {m: {"saldo": [], "S12": []} for m in ("taxas", "ets", "comb", "ingenuo")}
    for T in origens:
        r = projetar(df, T, H, cfg)
        s0 = df.S.loc[T]
        for m in mae:
            traj = trajetoria_estoque(s0, r[m])
            for k, d in enumerate(_meses_a_frente(T, H), 1):
                if d > T_fim:
                    break
                if k <= 12:
                    mae[m]["saldo"].append(abs((r[m][k - 1, 0] - r[m][k - 1, 1]) - df.saldo.loc[d]))
                if k == 12:
                    mae[m]["S12"].append(abs(traj[k - 1] - df.S.loc[d]))
                if m == "comb":
                    erros_S[k].append(df.S.loc[d] - traj[k - 1])
    q_lo, q_hi = cfg.quantis
    faixa = {}
    validos = [k for k, v in erros_S.items() if len(v) >= cfg.min_obs_quantil]
    k_max = max(validos)
    for k in range(1, H + 1):
        if k in validos:
            faixa[k] = (float(np.quantile(erros_S[k], q_lo)), float(np.quantile(erros_S[k], q_hi)))
        else:  # horizonte sem erros suficientes: escala o último quantil por sqrt(k/k_max)
            lo, hi = faixa[k_max]
            f = np.sqrt(k / k_max)
            faixa[k] = (lo * f, hi * f)
    # a incerteza não pode diminuir com o horizonte: faixa monotonicamente não-decrescente
    for k in range(2, H + 1):
        faixa[k] = (min(faixa[k][0], faixa[k - 1][0]), max(faixa[k][1], faixa[k - 1][1]))
    metr = {m: {kk: (round(float(np.mean(v)), 1) if v else None) for kk, v in d.items()} for m, d in mae.items()}
    return {"faixa": faixa, "mae": metr, "n_origens": len(origens), "horizonte_valido": k_max}


# --------------------------------------------------------------------------- #
# 4. Edições (revisão): um DuckDB por território, fora do warehouse
# --------------------------------------------------------------------------- #
def arquivo_edicoes(territorio: str, pasta: Path = PASTA) -> Path:
    return pasta / f"{territorio}.duckdb"


def ler_edicao_anterior(arquivo: Path, edicao: str, cfg: Config) -> dict[str, float] | None:
    """{competencia_alvo: estoque} da edição publicada mais recente com edicao < T."""
    if not arquivo.exists():
        return None
    con = duckdb.connect(str(arquivo), read_only=True)
    try:
        linhas = con.execute(
            f"""select competencia_alvo, estoque from {cfg.tabela_edicoes}
                where edicao = (select max(edicao) from {cfg.tabela_edicoes} where edicao < ?)""",
            [edicao],
        ).fetchall()
    except duckdb.CatalogException:
        linhas = []
    finally:
        con.close()
    return {c: float(e) for c, e in linhas} or None


def salvar_edicao(territorio: str, projecao: dict, pasta: Path = PASTA, cfg: Config | None = None) -> Path:
    """Grava a projeção mensal de uma edição (substitui, se a edição já existir). Chamada ao
    publicar (entrega_ia.py enviar), com o bloco `projecao` dos fatos do boletim enviado."""
    cfg = cfg or Config()
    arquivo = arquivo_edicoes(territorio, pasta)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(arquivo))
    try:
        con.execute(
            f"""create table if not exists {cfg.tabela_edicoes} (
                  edicao varchar, competencia_alvo varchar, admissoes double, desligamentos double,
                  saldo double, estoque double, estoque_lo double, estoque_hi double, gerado_em timestamp)"""
        )
        con.execute("begin")
        con.execute(f"delete from {cfg.tabela_edicoes} where edicao = ?", [projecao["edicao"]])
        agora = datetime.now()
        con.executemany(
            f"insert into {cfg.tabela_edicoes} values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(projecao["edicao"], p["competencia"], p["admissoes"], p["desligamentos"], p["saldo"],
              p["estoque"], p["estoque_lo"], p["estoque_hi"], agora) for p in projecao["projecao_mensal"]],
        )
        con.execute("commit")
    finally:
        con.close()
    return arquivo


# --------------------------------------------------------------------------- #
# 5. Orquestração
# --------------------------------------------------------------------------- #
def _sg(n: float) -> str:
    n = round(n)
    s = f"{abs(n):,}".replace(",", ".")
    return ("+" if n > 0 else "−" if n < 0 else "") + s


def _n(n: float) -> str:
    return f"{round(n):,}".replace(",", ".")


def gerar_projecao(warehouse: str | Path, estoque_ancora: float, *, territorio: str = "",
                   complemento: dict | None = None, cfg: Config | None = None,
                   pasta: Path = PASTA) -> dict:
    """A projeção da edição (competência T = último mês da série), validada. Devolve um dict
    serializável em JSON (vai para fatos["projecao"]). Validação que bloqueia: ProjecaoBloqueada."""
    cfg = cfg or Config()
    df = reconstruir_estoque(carregar_fluxos(warehouse, complemento), estoque_ancora)
    T = df.index[-1]
    edicao = T.strftime("%Y-%m")
    # ano de referência: o ano corrente; na edição de dezembro, passa a ser o ano seguinte
    ano = T.year if T.month < 12 else T.year + 1
    dez_ano = pd.Timestamp(f"{ano}-12-01")
    dez_prox = pd.Timestamp(f"{ano + 1}-12-01")
    H = (dez_prox.year - T.year) * 12 + dez_prox.month - T.month   # até dez do ano seguinte

    r = projetar(df, T, H, cfg)
    bt = backtest(df, H, cfg)
    datas = _meses_a_frente(T, H)
    s0 = float(df.S.iloc[-1])
    c = r["comb"]
    estoque = trajetoria_estoque(s0, c)
    lo = np.array([estoque[k - 1] + bt["faixa"][k][0] for k in range(1, H + 1)])
    hi = np.array([estoque[k - 1] + bt["faixa"][k][1] for k in range(1, H + 1)])

    # validações que bloqueiam (seção 10)
    if not np.isfinite(c).all() or not np.isfinite(estoque).all():
        raise ProjecaoBloqueada("Valores ausentes (NaN) na projeção.")
    if (c < 0).any():
        raise ProjecaoBloqueada("Admissões ou desligamentos negativos na projeção.")
    if not np.allclose(np.diff(np.r_[s0, estoque]), c[:, 0] - c[:, 1]):
        raise ProjecaoBloqueada("Identidade estoque-fluxo violada.")
    if not ((lo <= estoque + 1e-9).all() and (estoque <= hi + 1e-9).all()):
        raise ProjecaoBloqueada("A faixa provável não contém a projeção central.")

    i_dez = list(datas).index(dez_ano)
    i_prox = H - 1
    S_dez_ano_ant = float(df.S.loc[pd.Timestamp(f"{ano - 1}-12-01")])
    kpis = {
        "estoque_dez_ano": float(estoque[i_dez]),
        "estoque_dez_ano_faixa": [float(lo[i_dez]), float(hi[i_dez])],
        "saldo_ano": float(estoque[i_dez] - S_dez_ano_ant),
        "saldo_ano_faixa": [float(lo[i_dez] - S_dez_ano_ant), float(hi[i_dez] - S_dez_ano_ant)],
        "estoque_dez_prox": float(estoque[i_prox]),
        "estoque_dez_prox_faixa": [float(lo[i_prox]), float(hi[i_prox])],
    }

    # revisão frente à edição anterior publicada; sem ela, recalcula com dados até T-1
    arquivo = arquivo_edicoes(territorio, pasta) if territorio else None
    serie_anterior = ler_edicao_anterior(arquivo, edicao, cfg) if arquivo else None
    origem = "armazenada"
    if serie_anterior is None:
        origem = "recalculada"
        Tp = T - pd.DateOffset(months=1)
        Hp = H + 1
        rp = projetar(df.loc[:Tp], Tp, Hp, cfg)
        tp = trajetoria_estoque(df.S.loc[Tp], rp["comb"])
        serie_anterior = dict(zip(_meses_a_frente(Tp, Hp).strftime("%Y-%m"), map(float, tp)))
    revisao = {
        "origem": origem,
        "proj_anterior_mes_atual": serie_anterior.get(edicao),
        "realizado_mes_atual": s0,
        "proj_anterior_dez_ano": serie_anterior.get(dez_ano.strftime("%Y-%m")),
        "proj_atual_dez_ano": kpis["estoque_dez_ano"],
    }

    avisos = []
    mae_c, mae_i = bt["mae"]["comb"]["S12"], bt["mae"]["ingenuo"]["S12"]
    if mae_c and mae_i and mae_c > mae_i:
        avisos.append(f"Combinação pior que o sazonal ingênuo no backtest (MAE do estoque 12 meses à frente: "
                      f"{mae_c} contra {mae_i}). Revisar antes de publicar.")
    largura_dez = kpis["estoque_dez_ano_faixa"][1] - kpis["estoque_dez_ano_faixa"][0]
    if revisao["proj_anterior_dez_ano"] is not None and \
            abs(revisao["proj_atual_dez_ano"] - revisao["proj_anterior_dez_ano"]) > largura_dez:
        avisos.append("A revisão da projeção de dezembro é maior que a largura da faixa: possível quebra, "
                      "mudança de base ou erro de dados.")
    if origem == "recalculada":
        avisos.append("Nenhuma edição anterior publicada: a revisão usa a projeção recalculada com dados até o "
                      "mês anterior.")

    inicio_graf = pd.Timestamp(f"{ano - cfg.janela_grafico_inicio_anos_atras}-01-01")
    hist = df.loc[inicio_graf:]
    res = {
        "edicao": edicao,
        "ano": ano,
        "ano_prox": ano + 1,
        "estoque_ancora": float(estoque_ancora),
        "kpis": kpis,
        "revisao": revisao,
        "serie_anterior": {k: v for k, v in sorted(serie_anterior.items())},
        "historico": [{"competencia": d.strftime("%Y-%m"), "estoque": float(v)} for d, v in hist.S.items()],
        "estoque_mes_anterior": float(df.S.iloc[-2]),
        "projecao_mensal": [
            {"competencia": d.strftime("%Y-%m"), "admissoes": float(c[i, 0]), "desligamentos": float(c[i, 1]),
             "saldo": float(c[i, 0] - c[i, 1]), "estoque": float(estoque[i]), "estoque_lo": float(lo[i]),
             "estoque_hi": float(hi[i])}
            for i, d in enumerate(datas)],
        "backtest": {"mae": bt["mae"], "n_origens": bt["n_origens"], "horizonte_valido": bt["horizonte_valido"]},
        "avisos": avisos,
    }
    res["texto"] = redigir_texto(res)
    return _arredondar(res)


def _arredondar(obj, casas: int = 2):
    """Arredonda os floats (o JSON entra no hash dos fatos; ruído na 12ª casa não deve mudar o hash)."""
    if isinstance(obj, float):
        return round(obj, casas)
    if isinstance(obj, dict):
        return {k: _arredondar(v, casas) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_arredondar(v, casas) for v in obj]
    return obj


# --------------------------------------------------------------------------- #
# 6. Textos (modelos fixos da especificação, seção 7)
# --------------------------------------------------------------------------- #
def redigir_texto(res: dict) -> dict:
    k, rv = res["kpis"], res["revisao"]
    lo, hi = k["saldo_ano_faixa"]
    if lo > 0:
        leitura = "o que indica crescimento do estoque até o fim do ano"
    elif hi < 0:
        leitura = "o que indica retração do estoque até o fim do ano"
    else:
        leitura = "o que indica estabilidade em relação ao nível atual"
    a, b = k["estoque_dez_ano_faixa"]
    paragrafo = (
        f"Com base no padrão histórico de admissões e desligamentos, o estoque de vínculos formais "
        f"deve encerrar {res['ano']} em torno de {_n(k['estoque_dez_ano'])}, com faixa provável entre "
        f"{_n(a)} e {_n(b)}. O saldo projetado para o ano é de {_sg(k['saldo_ano'])} vínculos, {leitura}."
    )
    revisao = None
    if rv["proj_anterior_mes_atual"] is not None and rv["proj_anterior_dez_ano"] is not None:
        mes = int(res["edicao"][5:])
        revisao = (
            f"Na edição anterior, a projeção para o estoque de {MESES_EXT[mes - 1]} era de "
            f"{_n(rv['proj_anterior_mes_atual'])}; o resultado foi {_n(rv['realizado_mes_atual'])} "
            f"({_sg(rv['realizado_mes_atual'] - rv['proj_anterior_mes_atual'])}). Com isso, a projeção para "
            f"dezembro de {res['ano']} passou de {_n(rv['proj_anterior_dez_ano'])} para "
            f"{_n(rv['proj_atual_dez_ano'])} ({_sg(rv['proj_atual_dez_ano'] - rv['proj_anterior_dez_ano'])})."
        )
    legenda = (f"Estoque de vínculos formais, jan/{str(res['ano'] - 1)[2:]} a dez/{str(res['ano_prox'])[2:]}. "
               "Faixa provável: intervalo em que o resultado real ficou em 8 de cada 10 testes com dados passados.")
    nota = ("Projeção experimental: média de dois métodos (taxas sazonais de admissão e desligamento sobre o "
            "estoque e suavização exponencial de Holt-Winters). A faixa provável corresponde aos percentis de "
            "10% e 90% dos erros observados em testes com dados passados. Revista a cada edição.")
    bt = res["backtest"]
    fragilidades = (
        "Fragilidades conhecidas: a série do Novo CAGED é curta (começa em 2020, e 2020 fica fora das taxas "
        f"por causa da pandemia); o teste com dados passados começa em dezembro de 2022 ({bt['n_origens']} "
        f"pontos de partida), e acima de {bt['horizonte_valido']} meses à frente a faixa é estendida por fórmula; "
        "a faixa resume erros passados e não cobre mudanças sem precedente; fatores externos ao CAGED não "
        "entram; declarações fora do prazo, exclusões e revisões do estoque de referência do MTE mudam o ponto "
        f"de partida. Erro médio do estoque 12 meses à frente nos testes: {_n(bt['mae']['comb']['S12'])} "
        f"vínculos (referência que repete o ano anterior: {_n(bt['mae']['ingenuo']['S12'])})."
    )
    return {"paragrafo": paragrafo, "revisao": revisao, "legenda": legenda, "nota_metodologica": nota,
            "fragilidades": fragilidades, "aviso_experimental": AVISO_EXPERIMENTAL}


# --------------------------------------------------------------------------- #
# 7. Nos fatos do boletim com IA
# --------------------------------------------------------------------------- #
def anexar(fatos: dict, warehouse: Path, pasta: Path = PASTA) -> dict:
    """Acrescenta fatos["projecao"] (ou fatos["projecao_ausente"], com o motivo) e recalcula o hash.
    O âncora é o estoque da página 1; a competência da série tem de ser a do boletim."""
    import fatos as fatos_mod

    territorio = fatos["territorio"]["codigo"]
    competencia = str(fatos["competencia"])
    ancora = (fatos.get("panorama", {}).get("estoque") or {}).get("valor")
    saida = {k: v for k, v in fatos.items() if k not in ("projecao", "projecao_ausente", "hash")}
    try:
        if ancora is None:
            raise ProjecaoBloqueada("Sem estoque na página 1 (mart_estoque): não há âncora.")
        res = gerar_projecao(warehouse, ancora, territorio=territorio, pasta=pasta)
        if res["edicao"].replace("-", "") != competencia:
            raise ProjecaoBloqueada(f"A série termina em {res['edicao']}, não na competência do boletim ({competencia}).")
        if res["estoque_ancora"] != ancora:  # aviso da seção 10; aqui o âncora vem da própria página 1
            res["avisos"].append("O estoque âncora difere do estoque publicado na página 1.")
        saida["projecao"] = res
    except Exception as e:  # a projeção é experimental: nunca derruba o boletim
        saida["projecao_ausente"] = f"{type(e).__name__}: {e}"[:300]
    saida["hash"] = fatos_mod.hash_dos_fatos(saida)
    return saida


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Projeção do emprego formal (seção Perspectivas, F21).")
    ap.add_argument("warehouse")
    ap.add_argument("--estoque", type=float, required=True, help="estoque âncora (o da página 1 do boletim)")
    ap.add_argument("--complemento", help='JSON, ex.: {"2026-08":[1028,1107]} (só para o teste de aceitação)')
    ap.add_argument("--territorio", default="", help="lê a edição anterior em --edicoes/<territorio>.duckdb")
    ap.add_argument("--edicoes", default=str(PASTA))
    a = ap.parse_args()
    res = gerar_projecao(a.warehouse, a.estoque, territorio=a.territorio,
                         complemento=json.loads(a.complemento) if a.complemento else None, pasta=Path(a.edicoes))
    k, rv, bt = res["kpis"], res["revisao"], res["backtest"]
    print(json.dumps(res["texto"], ensure_ascii=False, indent=2))
    print(f"origens no backtest: {bt['n_origens']}")
    print(f"estoque dez/{res['ano']}: {_n(k['estoque_dez_ano'])} (faixa {_n(k['estoque_dez_ano_faixa'][0])} a "
          f"{_n(k['estoque_dez_ano_faixa'][1])})")
    print(f"saldo {res['ano']}: {_sg(k['saldo_ano'])} (faixa {_sg(k['saldo_ano_faixa'][0])} a {_sg(k['saldo_ano_faixa'][1])})")
    print(f"estoque dez/{res['ano_prox']}: {_n(k['estoque_dez_prox'])} (faixa {_n(k['estoque_dez_prox_faixa'][0])} a "
          f"{_n(k['estoque_dez_prox_faixa'][1])})")
    p = res["projecao_mensal"][0]
    print(f"{p['competencia']}: adm. {_n(p['admissoes'])} / desl. {_n(p['desligamentos'])} / saldo {_sg(p['saldo'])}")
    print(f"revisão ({rv['origem']}): {_n(rv['proj_anterior_mes_atual'])} projetado contra "
          f"{_n(rv['realizado_mes_atual'])}; dez: de {_n(rv['proj_anterior_dez_ano'])} para {_n(rv['proj_atual_dez_ano'])}")
    print(f"MAE estoque 12m comb./ingênuo: {bt['mae']['comb']['S12']} / {bt['mae']['ingenuo']['S12']}")
    for w in res["avisos"]:
        print("AVISO:", w)
