"""
Geração do boletim (PDF) e da planilha (XLSX) de uma competência (F15).

Tudo sai do MART, nunca do raw (o .txt é apagado ao fim do run — F07). Os
números são lidos do warehouse tal como estão: nada aqui os recalcula nem os
interpreta (mesma regra de design do relatório planejado com CrewAI — número
vem de SQL determinístico).

O boletim gerado é o que vai ser ENVIADO e ARQUIVADO. Ele não se regenera
depois: o CAGED recebe declarações fora do prazo e exclusões que mudam meses
já publicados, então regenerar hoje daria números diferentes dos enviados.
"""

from dataclasses import dataclass
from pathlib import Path

import duckdb
from fpdf import FPDF
import xlsxwriter

MESES = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]

TITULO = "Boletim CAGED - Nossa Senhora do Socorro/SE"

# O que o leitor precisa saber para não superinterpretar o número.
NOTAS = [
    "Fonte: microdados do Novo CAGED (PDET/MTE), arquivo CAGEDMOV, recorte de Nossa Senhora do Socorro/SE.",
    "Só entram as movimentações declaradas DENTRO DO PRAZO. Declarações fora do prazo e exclusões "
    "(CAGEDFOR e CAGEDEXC) ainda não são incorporadas: os números de competências recentes tendem a "
    "ser revisados e podem diferir de uma consulta futura.",
    "Salários: apenas admissões com salário mensal informado (valor maior que zero). A mediana é a "
    "medida de referência; a média é mostrada para comparação.",
    "Índice de Palma: média dos 10% maiores salários de admissão dividida pela média dos 40% menores. "
    "Valores acima de 1,5 indicam desigualdade pronunciada.",
    "Saldo líquido = admissões - desligamentos.",
]


@dataclass
class Boletim:
    competencia: str            # AAAAMM
    linhas: list[dict]          # mart da competência, uma linha por grupamento
    serie: list[dict]           # totais por competência (até 12, terminando nesta)
    historico: list[dict]       # mart inteiro até esta competência (para a planilha)

    @property
    def total(self) -> dict:
        return _totais(self.linhas)

    def total_de(self, competencia: str) -> dict | None:
        for s in self.serie:
            if s["competencia"] == competencia:
                return s
        return None


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


def carregar(warehouse: Path, competencia: str) -> Boletim:
    """Lê o mart (somente leitura) e monta os dados do boletim de 'competencia'."""
    con = duckdb.connect(str(warehouse), read_only=True)
    try:
        cur = con.execute(
            "select competencia_mov, grupamento, admissoes, desligamentos, saldo_liquido, "
            "admissoes_com_salario_valido, salario_mediano_admissao, salario_medio_admissao, "
            "palma_index_admissao from mart_caged_mensal_grupamento "
            "where competencia_mov <= ? order by 1, 2",
            [int(competencia)],
        )
        colunas = [c[0] for c in cur.description]
        historico = [dict(zip(colunas, r)) for r in cur.fetchall()]
    finally:
        con.close()

    for h in historico:
        h["competencia_mov"] = str(h["competencia_mov"])
        h["saldo_liquido"] = int(h["saldo_liquido"])

    linhas = [h for h in historico if h["competencia_mov"] == competencia]
    if not linhas:
        raise ValueError(f"Competência {competencia} não está no mart.")

    por_comp: dict[str, list[dict]] = {}
    for h in historico:
        por_comp.setdefault(h["competencia_mov"], []).append(h)
    serie = [
        {"competencia": c, **_totais(ls)} for c, ls in sorted(por_comp.items())
    ][-12:]

    return Boletim(competencia=competencia, linhas=linhas, serie=serie, historico=historico)


# ------------------------------------------------------------------------ PDF

def _resumo(b: Boletim) -> list[str]:
    t = b.total
    frases = [
        f"Em {nome_competencia(b.competencia)}: {fmt_int(t['admissoes'])} admissões, "
        f"{fmt_int(t['desligamentos'])} desligamentos e saldo líquido de {fmt_sinal(t['saldo_liquido'])} empregos formais."
    ]
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
    trazer biblioteca gráfica (a VM tem pouca memória)."""
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
        h = abs(v) / maximo * (metade - 4)
        x = x0 + i * passo + (passo - barra) / 2
        if v >= 0:
            pdf.set_fill_color(38, 102, 58)
            pdf.rect(x, eixo - h, barra, h, style="F")
            pdf.set_xy(x - 2, eixo - h - 4)
        else:
            pdf.set_fill_color(165, 29, 45)
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
    cab = ["Grupamento", "Admissões", "Deslig.", "Saldo", "Sal. mediano", "Sal. médio", "Palma"]
    with pdf.table(
        col_widths=(52, 20, 20, 20, 30, 30, 18),
        text_align=("LEFT",) + ("RIGHT",) * 6,
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
            linha.cell(fmt_brl(l["salario_mediano_admissao"]))
            linha.cell(fmt_brl(l["salario_medio_admissao"]))
            linha.cell(fmt_num(l["palma_index_admissao"], 2))
        t = b.total
        linha = tabela.row()
        linha.cell("Total")
        linha.cell(fmt_int(t["admissoes"]))
        linha.cell(fmt_int(t["desligamentos"]))
        linha.cell(fmt_sinal(t["saldo_liquido"]))
        linha.cell("-")
        linha.cell("-")
        linha.cell("-")
    pdf.ln(6)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, _latin1(f"Saldo líquido nos últimos {len(b.serie)} meses"), new_x="LMARGIN", new_y="NEXT")
    _grafico_saldo(pdf, b.serie)

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, "Notas", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=8)
    for nota in NOTAS:
        pdf.multi_cell(0, 4, _latin1("- " + nota), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(0.5)

    pdf.output(str(destino))


# ----------------------------------------------------------------------- XLSX

_COLUNAS = [
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


def gerar_xlsx(b: Boletim, destino: Path) -> None:
    wb = xlsxwriter.Workbook(str(destino))
    negrito = wb.add_format({"bold": True, "bg_color": "#E8ECEF", "border": 1, "text_wrap": True})
    inteiro = wb.add_format({"num_format": "#,##0"})
    dinheiro = wb.add_format({"num_format": "R$ #,##0.00"})
    razao = wb.add_format({"num_format": "0.00"})
    total_int = wb.add_format({"bold": True, "num_format": "#,##0", "top": 1})
    total_txt = wb.add_format({"bold": True, "top": 1})
    formatos = {
        "admissoes": inteiro, "desligamentos": inteiro, "saldo_liquido": inteiro,
        "admissoes_com_salario_valido": inteiro, "salario_mediano_admissao": dinheiro,
        "salario_medio_admissao": dinheiro, "palma_index_admissao": razao,
    }

    def aba(nome: str, linhas: list[dict], com_total: bool) -> None:
        ws = wb.add_worksheet(nome)
        for j, (_, titulo) in enumerate(_COLUNAS):
            ws.write(0, j, titulo, negrito)
        for i, l in enumerate(linhas, start=1):
            for j, (chave, _) in enumerate(_COLUNAS):
                v = l[chave]
                if v is None:
                    ws.write_blank(i, j, None)
                else:
                    ws.write(i, j, v, formatos.get(chave))
        if com_total:
            fim = len(linhas) + 1
            ws.write(fim, 0, "Total", total_txt)
            ws.write(fim, 1, "", total_txt)
            for j, chave in ((2, "admissoes"), (3, "desligamentos"), (4, "saldo_liquido")):
                ws.write(fim, j, sum(l[chave] for l in linhas), total_int)
        ws.set_column(0, 0, 13)
        ws.set_column(1, 1, 44)
        ws.set_column(2, 8, 16)
        ws.set_row(0, 32)
        ws.freeze_panes(1, 0)

    aba(f"Competência {b.competencia[:4]}-{b.competencia[4:]}", b.linhas, com_total=True)
    aba("Série histórica", b.historico, com_total=False)

    ws = wb.add_worksheet("Notas")
    ws.set_column(0, 0, 120)
    ws.write(0, 0, f"{TITULO} - {nome_competencia(b.competencia)}", wb.add_format({"bold": True}))
    for i, nota in enumerate(NOTAS, start=2):
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
