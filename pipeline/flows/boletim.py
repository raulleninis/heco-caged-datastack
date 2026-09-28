"""
Geração do boletim (PDF) e da planilha (XLSX) de uma competência (F15, F12).

Tudo sai do MART, nunca do raw (o .txt é apagado ao fim do run — F07). Os
números são lidos do warehouse tal como estão: nada aqui os recalcula nem os
interpreta (mesma regra de design do relatório planejado com CrewAI — número
vem de SQL determinístico).

Contagens (admissões, desligamentos, saldo): vêm do mart RECONCILIADO
(mart_caged_reconciliado, F12) = MOV + FOR - EXC, com a marcação provisório x
consolidado. Se o warehouse ainda não tem esse mart (anterior à F12), cai no
mart só-MOV e o boletim diz isso. Salários: sempre do mart só-MOV (a mediana de
quem entrou fora do prazo não se soma à do MOV).

Estoque e taxa de variação (F16): vêm do mart_estoque, só para o território do boletim. São uma
ESTIMATIVA a partir do marco zero e só aparecem quando existem: sem o mart, ou sem marco zero
para o território, o boletim sai sem eles, e nada mais muda.

O boletim gerado é o que vai ser ENVIADO e ARQUIVADO. Ele não se regenera
depois: o CAGED recebe declarações fora do prazo e exclusões que mudam meses
já publicados, então regenerar hoje daria números diferentes dos enviados.
"""

from dataclasses import dataclass, field
from pathlib import Path

import duckdb
from fpdf import FPDF
import xlsxwriter

MESES = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]

TITULO = "Boletim CAGED - Nossa Senhora do Socorro/SE"

# Território do boletim no mart_estoque. É o mesmo município da var `municipio_boletim` do dbt
# (dbt_project.yml), que filtra os marts de fluxo e salário.
TERRITORIO = "280480"

NOTA_ESTOQUE = (
    "Estoque: estimativa a partir de marco zero, em vínculos formais ao fim do mês. O marco é o "
    "estoque do painel do Novo CAGED do MTE em março/2020; a cada mês desde abril/2020 soma-se o "
    "saldo reconciliado. Conferido com o painel do MTE (idêntico em 14 competências de 2020 a 2026). "
    "É revisado quando chegam declarações fora do prazo e exclusões. Variação no mês = saldo do mês "
    "dividido pelo estoque do mês anterior."
)

# O que o leitor precisa saber para não superinterpretar o número.
NOTAS_RECONCILIADO = [
    "Fonte: microdados do Novo CAGED (PDET/MTE), recorte de Nossa Senhora do Socorro/SE.",
    "Saldo reconciliado: movimentações declaradas dentro do prazo (CAGEDMOV) + declaradas fora do "
    "prazo (CAGEDFOR) - exclusões (CAGEDEXC), com as declarações recebidas até {ultima}.",
    "PROVISÓRIO: competência com menos de 12 meses. O CAGED recebe declarações fora do prazo por cerca "
    "de um ano, então o saldo ainda pode ser revisado. CONSOLIDADO: mais antiga que isso; só exclusões "
    "tardias ainda podem alterá-la.",
    "Salários: apenas admissões declaradas dentro do prazo (CAGEDMOV) com salário mensal informado "
    "(valor maior que zero). A mediana é a medida de referência; a média é mostrada para comparação.",
    "Índice de Palma: média dos 10% maiores salários de admissão dividida pela média dos 40% menores. "
    "Valores acima de 1,5 indicam desigualdade pronunciada.",
    "Saldo líquido = admissões - desligamentos.",
]

NOTAS_SO_MOV = [
    "Fonte: microdados do Novo CAGED (PDET/MTE), arquivo CAGEDMOV, recorte de Nossa Senhora do Socorro/SE.",
    "Só entram as movimentações declaradas DENTRO DO PRAZO. Declarações fora do prazo e exclusões "
    "(CAGEDFOR e CAGEDEXC) não foram incorporadas: os números de competências recentes tendem a "
    "ser revisados e podem diferir de uma consulta futura.",
    "Salários: apenas admissões com salário mensal informado (valor maior que zero). A mediana é a "
    "medida de referência; a média é mostrada para comparação.",
    "Índice de Palma: média dos 10% maiores salários de admissão dividida pela média dos 40% menores. "
    "Valores acima de 1,5 indicam desigualdade pronunciada.",
    "Saldo líquido = admissões - desligamentos.",
]

PROVISORIO = "provisório"
CONSOLIDADO = "consolidado"


@dataclass
class Boletim:
    competencia: str            # AAAAMM
    linhas: list[dict]          # mart da competência, uma linha por grupamento
    serie: list[dict]           # totais por competência (até 12, terminando nesta): o gráfico
    historico: list[dict]       # mart inteiro até esta competência (para a planilha)
    totais: dict[str, dict] = field(default_factory=dict)  # totais de TODAS as competências
    reconciliado: bool = False  # True se as contagens vêm do mart reconciliado (F12)
    ultima_competencia: str | None = None   # última competência carregada (corte do consolidado)
    situacao: str | None = None             # desta competência: provisório | consolidado
    # F16: estoque e taxa do total do território por competência (vazio sem mart_estoque)
    estoque_totais: dict[str, dict] = field(default_factory=dict)

    @property
    def tem_estoque(self) -> bool:
        return self.estoque_total is not None

    @property
    def estoque_total(self) -> dict | None:
        """{'estoque', 'taxa_variacao_mensal'} do total desta competência, ou None se não houver
        estoque (sem mart_estoque, sem marco zero, ou competência anterior ao marco)."""
        t = self.estoque_totais.get(self.competencia)
        return t if t and t["estoque"] is not None else None

    @property
    def total(self) -> dict:
        return _totais(self.linhas)

    def total_de(self, competencia: str) -> dict | None:
        """Totais de uma competência qualquer do histórico. Não pode usar `serie`: ela é só a
        janela do gráfico (12 meses) e o mesmo mês do ano anterior está a 13 meses de distância."""
        return self.totais.get(competencia)

    @property
    def total_so_mov(self) -> int | None:
        """Saldo só-MOV da competência, para mostrar o quanto a reconciliação mudou."""
        if not self.reconciliado:
            return None
        return sum(l["saldo_mov"] for l in self.linhas)


# ---------------------------------------------------------------- formatação

def nome_competencia(competencia: str) -> str:
    """'202607' -> 'julho/2026'"""
    return f"{MESES[int(competencia[4:]) - 1]}/{competencia[:4]}"


def competencia_deslocada(competencia: str, meses: int) -> str:
    total = int(competencia[:4]) * 12 + int(competencia[4:]) - 1 + meses
    return f"{total // 12}{total % 12 + 1:02d}"


def fmt_int(n: int | None) -> str:
    return "-" if n is None else f"{n:,}".replace(",", ".")


def fmt_sinal(n: int) -> str:
    return f"+{fmt_int(n)}" if n > 0 else fmt_int(n)


def fmt_num(x: float | None, casas: int = 2) -> str:
    if x is None:
        return "-"
    return f"{x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_brl(x: float | None) -> str:
    return "-" if x is None else f"R$ {fmt_num(x)}"


def fmt_pct(x: float | None) -> str:
    """Fração -> '+0,18%' / '-0,33%'."""
    if x is None:
        return "-"
    return ("+" if x > 0 else "") + fmt_num(x * 100) + "%"


def _latin1(texto: str) -> str:
    """As fontes embutidas do PDF só têm Latin-1 (acentos do português cabem;
    travessão, aspas curvas etc. não). Troca o resto por '?', sem quebrar."""
    return texto.encode("latin-1", "replace").decode("latin-1")


# ---------------------------------------------------------------------- dados

def _totais(linhas: list[dict]) -> dict:
    return {
        "admissoes": sum(l["admissoes"] for l in linhas),
        "desligamentos": sum(l["desligamentos"] for l in linhas),
        "saldo_liquido": sum(l["saldo_liquido"] for l in linhas),
    }


def _consulta(con, sql: str, params: list) -> list[dict]:
    cur = con.execute(sql, params)
    colunas = [c[0] for c in cur.description]
    return [dict(zip(colunas, r)) for r in cur.fetchall()]


_COLUNAS_RECONCILIADO = (
    "competencia_mov, grupamento, admissoes_mov, desligamentos_mov, saldo_mov, "
    "admissoes_fora_prazo, desligamentos_fora_prazo, saldo_fora_prazo, "
    "admissoes_excluidas, desligamentos_excluidos, saldo_exclusoes, "
    "admissoes_consolidadas, desligamentos_consolidados, saldo_consolidado, "
    "ultima_competencia_carregada, defasagem_meses, situacao"
)


def carregar(warehouse: Path, competencia: str) -> Boletim:
    """Lê o mart (somente leitura) e monta os dados do boletim de 'competencia'."""
    con = duckdb.connect(str(warehouse), read_only=True)
    try:
        so_mov = _consulta(
            con,
            "select competencia_mov, grupamento, admissoes, desligamentos, saldo_liquido, "
            "admissoes_com_salario_valido, salario_mediano_admissao, salario_medio_admissao, "
            "palma_index_admissao from mart_caged_mensal_grupamento "
            "where competencia_mov <= ? order by 1, 2",
            [int(competencia)],
        )
        tem_reconciliado = con.execute(
            "select 1 from information_schema.tables where table_name = 'mart_caged_reconciliado'"
        ).fetchone()
        reconciliado = (
            _consulta(
                con,
                f"select {_COLUNAS_RECONCILIADO} from mart_caged_reconciliado where competencia_mov <= ? order by 1, 2",
                [int(competencia)],
            )
            if tem_reconciliado else []
        )
        estoque, estoque_totais = _carregar_estoque(con, competencia)
    finally:
        con.close()

    for h in so_mov:
        h["competencia_mov"] = str(h["competencia_mov"])
        h["saldo_liquido"] = int(h["saldo_liquido"])

    if reconciliado:
        historico = _mesclar(so_mov, reconciliado)
    else:
        historico = so_mov

    if not any(h["competencia_mov"] == competencia for h in historico):
        raise ValueError(f"Competência {competencia} não está no mart.")
    historico = _com_estoque(historico, estoque)
    linhas = [h for h in historico if h["competencia_mov"] == competencia]

    por_comp: dict[str, list[dict]] = {}
    for h in historico:
        por_comp.setdefault(h["competencia_mov"], []).append(h)
    totais = {}
    for c, ls in sorted(por_comp.items()):
        totais[c] = {"competencia": c, **_totais(ls)}
        if reconciliado:
            totais[c]["situacao"] = ls[0]["situacao"]
    serie = list(totais.values())[-12:]

    return Boletim(
        competencia=competencia,
        linhas=linhas,
        serie=serie,
        historico=historico,
        totais=totais,
        reconciliado=bool(reconciliado),
        ultima_competencia=str(linhas[0]["ultima_competencia_carregada"]) if reconciliado else None,
        situacao=linhas[0]["situacao"] if reconciliado else None,
        estoque_totais=estoque_totais,
    )


def _carregar_estoque(con, competencia: str) -> tuple[dict, dict]:
    """(por (competência, grupamento), por competência) do mart_estoque do TERRITORIO. Os totais
    do território (estoque e taxa) saem de SQL, como os demais números do boletim. Vazios se o
    mart não existir (warehouse anterior à F16)."""
    if not con.execute(
        "select 1 from information_schema.tables where table_name = 'mart_estoque'"
    ).fetchone():
        return {}, {}
    por_grupo = {
        (str(r["competencia_mov"]), r["grupamento"]): r
        for r in _consulta(
            con,
            "select competencia_mov, grupamento, saldo_consolidado, estoque, taxa_variacao_mensal "
            "from mart_estoque where territorio = ? and competencia_mov <= ?",
            [TERRITORIO, int(competencia)],
        )
    }
    totais = {
        str(r["competencia_mov"]): {
            "estoque": None if r["estoque"] is None else int(r["estoque"]),
            "taxa_variacao_mensal": r["taxa_variacao_mensal"],
        }
        for r in _consulta(
            con,
            "select competencia_mov, sum(estoque) as estoque, "
            "sum(saldo_consolidado) / nullif(lag(sum(estoque)) over (order by competencia_mov), 0) "
            "as taxa_variacao_mensal "
            "from mart_estoque where territorio = ? and competencia_mov <= ? group by 1",
            [TERRITORIO, int(competencia)],
        )
    }
    return por_grupo, totais


def _com_estoque(historico: list[dict], estoque: dict) -> list[dict]:
    """Acrescenta estoque e taxa a cada linha. Um grupamento com estoque mas SEM movimentação no
    mês (fora dos marts de fluxo) entra com contagens zeradas, para a coluna de estoque fechar
    com o total do território."""
    saida = []
    for h in historico:
        e = estoque.get((h["competencia_mov"], h["grupamento"]), {})
        saida.append({**h, "estoque": _int_ou_none(e.get("estoque")),
                      "taxa_variacao_mensal": e.get("taxa_variacao_mensal")})
    presentes = {(h["competencia_mov"], h["grupamento"]) for h in historico}
    modelo = {}  # uma linha por competência: os campos que valem para o mês todo
    for h in historico:
        modelo.setdefault(h["competencia_mov"], h)
    for (c, g), e in estoque.items():
        if (c, g) in presentes or c not in modelo or not e.get("estoque"):
            continue
        linha = {k: (0 if k in _CONTAGENS else None) for k in modelo[c]}
        linha.update({k: modelo[c][k] for k in _DO_MES if k in modelo[c]})
        linha.update({"competencia_mov": c, "grupamento": g, "estoque": int(e["estoque"]),
                      "taxa_variacao_mensal": e.get("taxa_variacao_mensal")})
        saida.append(linha)
    return sorted(saida, key=lambda h: (h["competencia_mov"], h["grupamento"]))


# Na linha de um grupamento sem movimentação no mês: contagens zeradas, salários vazios, e os
# campos que valem para o mês todo copiados de outra linha da mesma competência.
_CONTAGENS = {
    "admissoes", "desligamentos", "saldo_liquido", "admissoes_com_salario_valido",
    "admissoes_mov", "desligamentos_mov", "saldo_mov", "saldo_fora_prazo", "saldo_exclusoes",
}
_DO_MES = {"situacao", "defasagem_meses", "ultima_competencia_carregada"}


def _int_ou_none(x) -> int | None:
    return None if x is None else int(x)


def _mesclar(so_mov: list[dict], reconciliado: list[dict]) -> list[dict]:
    """Contagens do mart reconciliado + salários do mart só-MOV, por (competência, grupamento).
    Um grupamento pode ter linha só no reconciliado (só FOR/EXC naquele mês): fica sem salário."""
    salarios = {(h["competencia_mov"], h["grupamento"]): h for h in so_mov}
    saida = []
    for r in reconciliado:
        chave = (str(r["competencia_mov"]), r["grupamento"])
        base = salarios.get(chave, {})
        saida.append({
            "competencia_mov": chave[0],
            "grupamento": r["grupamento"],
            "admissoes": int(r["admissoes_consolidadas"]),
            "desligamentos": int(r["desligamentos_consolidados"]),
            "saldo_liquido": int(r["saldo_consolidado"]),
            "admissoes_com_salario_valido": base.get("admissoes_com_salario_valido", 0),
            "salario_mediano_admissao": base.get("salario_mediano_admissao"),
            "salario_medio_admissao": base.get("salario_medio_admissao"),
            "palma_index_admissao": base.get("palma_index_admissao"),
            # componentes da reconciliação, para transparência
            "admissoes_mov": int(r["admissoes_mov"]),
            "desligamentos_mov": int(r["desligamentos_mov"]),
            "saldo_mov": int(r["saldo_mov"]),
            "saldo_fora_prazo": int(r["saldo_fora_prazo"]),
            "saldo_exclusoes": int(r["saldo_exclusoes"]),
            "situacao": r["situacao"],
            "defasagem_meses": int(r["defasagem_meses"]),
            "ultima_competencia_carregada": int(r["ultima_competencia_carregada"]),
        })
    return saida


# ------------------------------------------------------------------------ PDF

def _resumo(b: Boletim) -> list[str]:
    t = b.total
    frases = [
        f"Em {nome_competencia(b.competencia)}: {fmt_int(t['admissoes'])} admissões, "
        f"{fmt_int(t['desligamentos'])} desligamentos e saldo líquido de {fmt_sinal(t['saldo_liquido'])} empregos formais."
    ]
    if b.tem_estoque:
        e = b.estoque_total
        frases.append(
            f"Estoque estimado ao fim do mês: {fmt_int(e['estoque'])} vínculos formais "
            f"(variação de {fmt_pct(e['taxa_variacao_mensal'])} no mês; estimativa a partir de marco zero)."
        )
    if b.reconciliado:
        frases.append(
            f"Situação: {b.situacao.upper()}."
            + (" Ainda pode ser revisada por declarações fora do prazo e exclusões." if b.situacao == PROVISORIO
               else " Só exclusões tardias ainda podem alterá-la.")
        )
        so_mov = b.total_so_mov
        if so_mov != t["saldo_liquido"]:
            frases.append(
                f"Saldo declarado dentro do prazo (CAGEDMOV): {fmt_sinal(so_mov)}; depois das declarações fora do "
                f"prazo e das exclusões: {fmt_sinal(t['saldo_liquido'])}."
            )
    for rotulo, desloc in (("mês anterior", -1), ("mesmo mês do ano anterior", -12)):
        ref = b.total_de(competencia_deslocada(b.competencia, desloc))
        if ref is None:
            frases.append(f"Comparação com o {rotulo}: indisponível (competência fora do warehouse).")
        else:
            frases.append(
                f"Saldo líquido no {rotulo} ({nome_competencia(competencia_deslocada(b.competencia, desloc))}): "
                f"{fmt_sinal(ref['saldo_liquido'])}."
            )
    return frases


def _grafico_saldo(pdf: FPDF, serie: list[dict]) -> None:
    """Barras do saldo líquido total por competência. Desenhado à mão para não
    trazer biblioteca gráfica (a VM tem pouca memória). Barras claras = provisório."""
    x0, largura, altura = pdf.l_margin, pdf.epw, 42
    topo = pdf.get_y() + 4
    maximo = max((abs(s["saldo_liquido"]) for s in serie), default=0) or 1
    metade = altura / 2
    eixo = topo + metade
    n = len(serie)
    passo = largura / n
    barra = passo * 0.6

    pdf.set_draw_color(120)
    pdf.line(x0, eixo, x0 + largura, eixo)
    pdf.set_font("Helvetica", size=7)
    for i, s in enumerate(serie):
        v = s["saldo_liquido"]
        provisorio = s.get("situacao") == PROVISORIO
        h = abs(v) / maximo * (metade - 4)
        x = x0 + i * passo + (passo - barra) / 2
        if v >= 0:
            pdf.set_fill_color(*((150, 200, 165) if provisorio else (38, 102, 58)))
            pdf.rect(x, eixo - h, barra, h, style="F")
            pdf.set_xy(x - 2, eixo - h - 4)
        else:
            pdf.set_fill_color(*((225, 155, 165) if provisorio else (165, 29, 45)))
            pdf.rect(x, eixo, barra, h, style="F")
            pdf.set_xy(x - 2, eixo + h)
        pdf.cell(barra + 4, 4, fmt_sinal(v), align="C")
        pdf.set_xy(x - 2, topo + altura + 1)
        c = s["competencia"]
        pdf.cell(barra + 4, 4, f"{c[4:]}/{c[2:4]}", align="C")
    pdf.set_y(topo + altura + 8)


def gerar_pdf(b: Boletim, destino: Path) -> None:
    pdf = FPDF(format="A4")
    pdf.set_margins(10, 12, 10)
    pdf.set_auto_page_break(True, margin=12)
    pdf.set_title(_latin1(f"{TITULO} - {nome_competencia(b.competencia)}"))
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 8, _latin1(TITULO), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=12)
    pdf.cell(0, 7, _latin1(f"Competência: {nome_competencia(b.competencia)}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font("Helvetica", size=10)
    for frase in _resumo(b):
        pdf.multi_cell(0, 5, _latin1(frase), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, "Por grupamento de atividade", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=8)
    # Com estoque (F16), a tabela ganha duas colunas; as larguras somam os 190 mm úteis nos dois casos.
    if b.tem_estoque:
        cab = ["Grupamento", "Admissões", "Deslig.", "Saldo", "Estoque*", "Var. mês*", "Sal. mediano", "Sal. médio", "Palma"]
        larguras = (39, 22, 17, 16, 20, 16, 23, 23, 14)
    else:
        cab = ["Grupamento", "Admissões", "Deslig.", "Saldo", "Sal. mediano", "Sal. médio", "Palma"]
        larguras = (52, 20, 20, 20, 30, 30, 18)
    with pdf.table(
        col_widths=larguras,
        text_align=("LEFT",) + ("RIGHT",) * (len(cab) - 1),
        line_height=4.5,
    ) as tabela:
        linha = tabela.row()
        for c in cab:
            linha.cell(_latin1(c))
        for l in b.linhas:
            linha = tabela.row()
            linha.cell(_latin1(l["grupamento"]))
            linha.cell(fmt_int(l["admissoes"]))
            linha.cell(fmt_int(l["desligamentos"]))
            linha.cell(fmt_sinal(l["saldo_liquido"]))
            if b.tem_estoque:
                linha.cell(fmt_int(l.get("estoque")))
                linha.cell(fmt_pct(l.get("taxa_variacao_mensal")))
            linha.cell(fmt_brl(l["salario_mediano_admissao"]))
            linha.cell(fmt_brl(l["salario_medio_admissao"]))
            linha.cell(fmt_num(l["palma_index_admissao"], 2))
        t = b.total
        linha = tabela.row()
        linha.cell("Total")
        linha.cell(fmt_int(t["admissoes"]))
        linha.cell(fmt_int(t["desligamentos"]))
        linha.cell(fmt_sinal(t["saldo_liquido"]))
        if b.tem_estoque:
            linha.cell(fmt_int(b.estoque_total["estoque"]))
            linha.cell(fmt_pct(b.estoque_total["taxa_variacao_mensal"]))
        linha.cell("-")
        linha.cell("-")
        linha.cell("-")
    if b.tem_estoque:
        pdf.set_font("Helvetica", size=7)
        pdf.cell(0, 4, _latin1("* Estimativa a partir de marco zero (ver notas)."), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    pdf.set_font("Helvetica", "B", 11)
    titulo_grafico = f"Saldo líquido nos últimos {len(b.serie)} meses"
    if b.reconciliado:
        titulo_grafico += " (barras claras = provisório)"
    pdf.cell(0, 6, _latin1(titulo_grafico), new_x="LMARGIN", new_y="NEXT")
    _grafico_saldo(pdf, b.serie)

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, "Notas", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=8)
    for nota in _notas(b):
        pdf.multi_cell(0, 4, _latin1("- " + nota), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(0.5)

    pdf.output(str(destino))


def _notas(b: Boletim) -> list[str]:
    if not b.reconciliado:
        notas = list(NOTAS_SO_MOV)
    else:
        ultima = nome_competencia(b.ultima_competencia) if b.ultima_competencia else "-"
        notas = [n.format(ultima=ultima) if "{ultima}" in n else n for n in NOTAS_RECONCILIADO]
    if b.tem_estoque:
        notas.insert(len(notas) - 1, NOTA_ESTOQUE)  # antes da definição de saldo líquido
    return notas


# ----------------------------------------------------------------------- XLSX

_COLUNAS_BASE = [
    ("competencia_mov", "Competência"),
    ("grupamento", "Grupamento"),
    ("admissoes", "Admissões"),
    ("desligamentos", "Desligamentos"),
    ("saldo_liquido", "Saldo líquido"),
    ("admissoes_com_salario_valido", "Admissões com salário válido"),
    ("salario_mediano_admissao", "Salário mediano (admissão)"),
    ("salario_medio_admissao", "Salário médio (admissão)"),
    ("palma_index_admissao", "Índice de Palma (admissão)"),
]

# Na versão reconciliada, a série histórica abre o saldo em seus componentes.
_COLUNAS_RECONCILIACAO = [
    ("saldo_mov", "Saldo só-MOV (no prazo)"),
    ("saldo_fora_prazo", "Efeito do fora do prazo"),
    ("saldo_exclusoes", "Efeito das exclusões"),
    ("situacao", "Situação"),
]

# Com estoque (F16): estimativa a partir de marco zero.
_COLUNAS_ESTOQUE = [
    ("estoque", "Estoque (estimativa, fim do mês)"),
    ("taxa_variacao_mensal", "Variação do estoque no mês"),
]


def gerar_xlsx(b: Boletim, destino: Path) -> None:
    wb = xlsxwriter.Workbook(str(destino))
    negrito = wb.add_format({"bold": True, "bg_color": "#E8ECEF", "border": 1, "text_wrap": True})
    inteiro = wb.add_format({"num_format": "#,##0"})
    dinheiro = wb.add_format({"num_format": "R$ #,##0.00"})
    razao = wb.add_format({"num_format": "0.00"})
    percentual = wb.add_format({"num_format": "0.00%"})
    total_int = wb.add_format({"bold": True, "num_format": "#,##0", "top": 1})
    total_txt = wb.add_format({"bold": True, "top": 1})
    formatos = {
        "admissoes": inteiro, "desligamentos": inteiro, "saldo_liquido": inteiro,
        "admissoes_com_salario_valido": inteiro, "salario_mediano_admissao": dinheiro,
        "salario_medio_admissao": dinheiro, "palma_index_admissao": razao,
        "saldo_mov": inteiro, "saldo_fora_prazo": inteiro, "saldo_exclusoes": inteiro,
        "estoque": inteiro, "taxa_variacao_mensal": percentual,
    }
    colunas = (
        _COLUNAS_BASE[:5]
        + (_COLUNAS_ESTOQUE if b.tem_estoque else [])
        + _COLUNAS_BASE[5:]
        + (_COLUNAS_RECONCILIACAO if b.reconciliado else [])
    )

    def aba(nome: str, linhas: list[dict], com_total: bool) -> None:
        ws = wb.add_worksheet(nome)
        for j, (_, titulo) in enumerate(colunas):
            ws.write(0, j, titulo, negrito)
        for i, l in enumerate(linhas, start=1):
            for j, (chave, _) in enumerate(colunas):
                v = l.get(chave)
                if v is None:
                    ws.write_blank(i, j, None)
                else:
                    ws.write(i, j, v, formatos.get(chave))
        if com_total:
            fim = len(linhas) + 1
            ws.write(fim, 0, "Total", total_txt)
            ws.write(fim, 1, "", total_txt)
            for j, (chave, _) in enumerate(colunas):
                if chave in ("admissoes", "desligamentos", "saldo_liquido", "saldo_mov", "saldo_fora_prazo", "saldo_exclusoes"):
                    ws.write(fim, j, sum(l.get(chave, 0) for l in linhas), total_int)
                elif chave == "estoque":
                    ws.write(fim, j, b.estoque_total["estoque"], total_int)
                elif chave == "taxa_variacao_mensal" and b.estoque_total["taxa_variacao_mensal"] is not None:
                    ws.write(fim, j, b.estoque_total["taxa_variacao_mensal"],
                             wb.add_format({"bold": True, "num_format": "0.00%", "top": 1}))
        ws.set_column(0, 0, 13)
        ws.set_column(1, 1, 44)
        ws.set_column(2, len(colunas) - 1, 16)
        ws.set_row(0, 32)
        ws.freeze_panes(1, 0)

    aba(f"Competência {b.competencia[:4]}-{b.competencia[4:]}", b.linhas, com_total=True)
    aba("Série histórica", b.historico, com_total=False)

    ws = wb.add_worksheet("Notas")
    ws.set_column(0, 0, 120)
    ws.write(0, 0, f"{TITULO} - {nome_competencia(b.competencia)}", wb.add_format({"bold": True}))
    for i, nota in enumerate(_notas(b), start=2):
        ws.write(i, 0, nota, wb.add_format({"text_wrap": True}))
    wb.close()


def gerar(warehouse: Path, competencia: str, pasta: Path) -> tuple[Path, Path]:
    """Gera boletim-AAAAMM.pdf e planilha-AAAAMM.xlsx em 'pasta'."""
    b = carregar(warehouse, competencia)
    pasta.mkdir(parents=True, exist_ok=True)
    pdf, xlsx = pasta / f"boletim-{competencia}.pdf", pasta / f"planilha-{competencia}.xlsx"
    gerar_pdf(b, pdf)
    gerar_xlsx(b, xlsx)
    return pdf, xlsx
