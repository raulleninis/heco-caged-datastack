"""Identidade e componentes PDF compartilhados. Renderização local, sem rede ou navegador.

O que é da instância (nome do território, instituição, órgão, logo) vem da seção [identidade] de
perfis/<territorio>.toml; sem ela, o boletim sai com a identidade neutra do produto (F18).
"""
import tomllib
from dataclasses import dataclass
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import MethodReturnValue

ASSETS = Path(__file__).resolve().parent / "assets"
PERFIS = Path(__file__).resolve().parent.parent / "perfis"
INK = (31, 41, 78)
BLUE = (68, 104, 176)
ACCENT = (103, 158, 213)
MUTED = (74, 85, 120)
NEGATIVE = (140, 47, 69)
ROSE = (199, 120, 138)
PALE = (201, 220, 240)
PAPER = (238, 241, 246)
RULE = (213, 219, 232)
ORANGE = (232, 134, 40)
BAR_BORDER_MM = .5 * 25.4 / 96  # 0,5 px CSS = 0,375 pt
BAR_BORDER_ALPHA = 0x10 / 255  # #00000010 (RGBA)


def number(value, decimals=0):
    if value is None:
        return "–"
    return f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".").replace("-", "−")


def signed(value):
    return ("+" if value is not None and value > 0 else "") + number(value)


def percent(value):
    """Recebe pontos percentuais (0,33 -> 0,33%)."""
    return "–" if value is None else number(value, 2) + "%"


def money(value):
    return "–" if value is None else "R$ " + number(value, 2)


def sign_color(value):
    return NEGATIVE if value is not None and value < 0 else BLUE


def fact(block, key):
    return (block.get(key) or {}).get("valor")


@dataclass(frozen=True)
class Identidade:
    territorio: str = ""        # nome do território nos títulos
    instituicao: str = ""       # abaixo de "BOLETIM CAGED" no cabeçalho e autor do PDF
    orgao: str = ""             # linha central do rodapé
    logo: Path | None = None


def carregar_identidade(territorio: str, pasta: Path = PERFIS) -> Identidade:
    """[identidade] de perfis/<territorio>.toml; `logo` é relativo à pasta dos perfis."""
    caminho = pasta / f"{territorio}.toml"
    dados = tomllib.loads(caminho.read_text(encoding="utf-8")).get("identidade", {}) if caminho.exists() else {}
    desconhecidos = set(dados) - {"territorio", "instituicao", "orgao", "logo"}
    if desconhecidos:
        raise ValueError(f"{caminho}: [identidade] com chaves desconhecidas {sorted(desconhecidos)}")
    logo = pasta / dados["logo"] if dados.get("logo") else None
    if logo is not None and not logo.exists():
        raise FileNotFoundError(f"{caminho}: logo {logo} não existe")
    return Identidade(dados.get("territorio", ""), dados.get("instituicao", ""), dados.get("orgao", ""), logo)


class BoletimPDF(FPDF):
    def __init__(self, title, *, identidade=Identidade(), status="provisório", prototype=True):
        super().__init__(format="A4")
        self.identidade, self.status, self.prototype = identidade, status, prototype
        self.section_number = 0
        self.set_margins(15.2, 13, 15.2)
        self.set_auto_page_break(True, margin=25)
        for family, style, filename in (
            ("Plex", "", "IBMPlexSans-Regular.ttf"),
            ("Plex", "B", "IBMPlexSans-SemiBold.ttf"),
            ("Archivo", "", "Archivo-Regular.ttf"),
            ("Archivo", "B", "Archivo-Bold.ttf"),
        ):
            self.add_font(family, style, str(ASSETS / "fonts" / filename))
        self.set_title(title)
        self.set_author(identidade.instituicao or "CAGED Analytics")
        self.set_creator("CAGED Analytics")
        self.alias_nb_pages()
        self.add_page()

    def font(self, size=11.25, *, bold=False, title=False, color=INK):
        self.set_font("Archivo" if title else "Plex", "B" if bold else "", size)
        self.set_text_color(*color)

    def at(self, x, y, w, text, *, size=9, bold=False, title=False, color=INK, align="L", line=4):
        self.font(size, bold=bold, title=title, color=color)
        self.set_xy(x, y)
        self.multi_cell(w, line, str(text), align=align, new_x="LMARGIN", new_y="NEXT")

    def lines(self, text, width, *, size=11.25, bold=False, title=False, line=6.2):
        self.font(size, bold=bold, title=title)
        return self.multi_cell(width, line, str(text), dry_run=True,
                               output=MethodReturnValue.LINES, new_x="LMARGIN", new_y="NEXT")

    def ensure(self, height):
        if self.get_y() + height > self.page_break_trigger:
            self.add_page()

    def rule(self, y, color=RULE, weight=.25, x=None, width=None):
        self.set_draw_color(*color)
        self.set_line_width(weight)
        x = self.l_margin if x is None else x
        self.line(x, y, x + (self.epw if width is None else width), y)

    def header(self):
        first = self.page_no() == 1
        y = 13
        if self.identidade.logo:
            self.image(str(self.identidade.logo), self.l_margin, y, h=14 if first else 9)
        badge = first and self.prototype
        right = self.w - self.r_margin - (33 if badge else 0)
        self.at(right - 66, y + 1, 66, "BOLETIM CAGED", title=True, bold=True, size=10, align="R")
        if self.identidade.instituicao:
            self.at(right - 66, y + 6, 66, self.identidade.instituicao, size=9, color=MUTED, align="R")
        if badge:
            x = self.w - self.r_margin - 29
            self.set_draw_color(*INK)
            self.set_line_width(.35)
            self.rect(x, y + 2, 29, 7)
            self.set_fill_color(*ORANGE)
            self.ellipse(x + 2.3, y + 4.7, 1.5, 1.5, style="F")
            self.at(x + 5, y + 3.2, 23, "PROTÓTIPO", size=8, bold=True, title=True)
        bottom = y + (19 if first else 14)
        self.rule(bottom, ACCENT, .5 if first else .3)
        self.set_xy(self.l_margin, bottom + 7)

    def footer(self):
        self.set_y(-21)
        y = self.get_y()
        self.rule(y)
        self.set_draw_color(*ORANGE)
        self.set_line_width(.35)
        self.ellipse(self.l_margin, y + 3, 3.5, 3.5)
        self.at(self.l_margin, y + 2.8, 3.5, "!", size=7, bold=True, align="C")
        # Marca discreta: o detalhe está na fonte da 1ª página e na nota metodológica (revisão de
        # 01/10/2026, item 14: a frase longa em toda página era ruído).
        if self.status == "provisório":
            note = "Dados provisórios, sujeitos a revisão."
        elif self.status == "consolidado":
            note = "Dados consolidados, ainda sujeitos a exclusões tardias."
        else:
            note = "Movimentações declaradas no prazo (MOV). Consulte as limitações na nota metodológica."
        self.at(self.l_margin + 5, y + 2.6, self.epw - 43, note, size=7.5, color=MUTED, line=3.5)
        self.at(self.w - self.r_margin - 36, y + 2.6, 36,
                f"Página {self.page_no()} de {{nb}}", size=8, title=True, color=MUTED, align="R")
        if self.identidade.orgao:
            self.at(self.l_margin, y + 12, self.epw, self.identidade.orgao, size=7.8, align="C")

    def paragraph(self, text, *, size=11.25, line=6.2, color=INK, bold=False, gap=3, align="J", markdown=False):
        """Texto corrido justificado (a última linha fica à esquerda). markdown=True aceita **negrito**."""
        if not text:
            return
        self.set_x(self.l_margin)
        self.font(size, bold=bold, color=color)
        self.multi_cell(self.epw, line, str(text), align=align, new_x="LMARGIN", new_y="NEXT", markdown=markdown)
        self.ln(gap)

    def cover(self, title, summary):
        self.paragraph("EMPREGO FORMAL · EDIÇÃO MENSAL", size=9, bold=True, color=BLUE, line=4, gap=3, align="L")
        self.font(23, title=True, bold=True)
        self.multi_cell(self.epw, 9, title, align="L", new_x="LMARGIN", new_y="NEXT")
        self.ln(4)
        self.paragraph(summary, size=12, line=6.8, gap=5)

    def section(self, title, *, numbered=True, reserve=18):
        height = len(self.lines(title, self.epw - 11, size=15.5, title=True, bold=True)) * 7
        self.ensure(height + reserve + 5)
        self.ln(3)
        y = self.get_y()
        if numbered:
            self.section_number += 1
            self.at(self.l_margin, y + 1.3, 9, f"{self.section_number:02}", size=10, title=True, bold=True, color=BLUE)
        self.at(self.l_margin + (11 if numbered else 0), y, self.epw - (11 if numbered else 0),
                title, size=15.5, title=True, bold=True, line=7)
        self.ln(3)

    def cards(self, cards):
        """Cartões: (rótulo, valor formatado, detalhe, cor). Até quatro por linha."""
        for start in range(0, len(cards), 4):
            group = cards[start:start + 4]
            width = self.epw / len(group)
            label_h = max(len(self.lines(c[0].upper(), width - 6, size=8.5, bold=True)) * 4 for c in group)
            note_h = max(len(self.lines(c[2], width - 6, size=8.5)) * 4 for c in group)
            height = 8 + label_h + 12 + note_h
            self.ensure(height + 4)
            y = self.get_y()
            self.rule(y, INK, .7)
            for i, (label, value, note, color) in enumerate(group):
                x = self.l_margin + i * width
                if i:
                    self.set_draw_color(*RULE)
                    self.line(x, y + 3, x, y + height - 2)
                self.at(x + 3, y + 4, width - 6, label.upper(), size=8.5, bold=True, color=MUTED)
                size = 28 if len(group) == 4 and i == 0 else 21
                self.font(size, bold=True, title=True)
                while self.get_string_width(value) > width - 8 and size > 12:
                    size -= 1
                    self.font(size, bold=True, title=True)
                self.at(x + 3, y + 5 + label_h, width - 6, value, size=size, title=True, bold=True, color=color, line=11)
                self.at(x + 3, y + 17 + label_h, width - 6, note, size=8.5, color=MUTED)
            self.rule(y + height)
            self.set_xy(self.l_margin, y + height + 4)

    def source(self, text):
        self.paragraph(text, size=8.5, line=4.1, color=MUTED, gap=5)

    def table(self, headers, rows, widths, *, bar_column=None, bar_values=None, highlights=(), colors=None):
        """Tabela com quebra por linha e cabeçalho repetido; barras vetoriais em escala comum."""
        widths = [self.epw * w / sum(widths) for w in widths]
        line = 4.3
        header_lines = [self.lines(t, w - 4, size=8, bold=True) for t, w in zip(headers, widths)]
        header_h = max(map(len, header_lines)) * line + 5
        maximum = max((abs(v) for v in (bar_values or []) if v is not None), default=0) or 1

        def draw_header():
            y, x = self.get_y(), self.l_margin
            for content, w in zip(header_lines, widths):
                self.at(x + 2, y + 2, w - 4, "\n".join(content), size=8, bold=True, color=MUTED,
                        align="L" if x == self.l_margin else "R", line=line)
                x += w
            self.rule(y + header_h, INK, .4)
            self.set_xy(self.l_margin, y + header_h)

        prepared = [[self.lines(t, w - 4, size=9) for t, w in zip(row, widths)] for row in rows]
        first_h = max(map(len, prepared[0])) * line + 5 if prepared else 0
        self.ensure(header_h + min(first_h, 45))
        draw_header()
        for index, cells in enumerate(prepared):
            height = max(map(len, cells)) * line + 5
            if self.get_y() + height > self.page_break_trigger:
                self.add_page()
                draw_header()
            # Nomes excepcionalmente extensos continuam na próxima página, sem cortes.
            offset = 0
            count = max(map(len, cells))
            while offset < count:
                capacity = int((self.page_break_trigger - self.get_y() - 5) / line)
                if capacity < 1:
                    self.add_page()
                    draw_header()
                    continue
                take = min(count - offset, capacity)
                height = take * line + 5
                y, x = self.get_y(), self.l_margin
                if index in highlights:
                    self.set_fill_color(*PAPER)
                    self.rect(x, y, self.epw, height, style="F")
                for column, (content, w) in enumerate(zip(cells, widths)):
                    if column == bar_column:
                        if offset == 0:
                            self.balance_bar(x + 2, y + height / 2, w - 4, bar_values[index], maximum)
                    else:
                        color = (colors or {}).get((index, column), INK)
                        self.at(x + 2, y + 2.5, w - 4, "\n".join(content[offset:offset + take]),
                                size=9, color=color, align="L" if column == 0 else "R", line=line)
                    x += w
                self.rule(y + height)
                self.set_xy(self.l_margin, y + height)
                offset += take
        self.ln(4)

    def bar_rect(self, x, y, width, height):
        """Mantém o preenchimento e aplica o contorno translúcido somente à barra."""
        if width <= 0 or height <= 0:
            return
        with self.local_context(draw_color=(0, 0, 0), line_width=BAR_BORDER_MM,
                                stroke_opacity=BAR_BORDER_ALPHA):
            self.rect(x, y, width, height, style="DF")

    def balance_bar(self, x, y, width, value, maximum):
        mid = x + width / 2
        self.set_draw_color(*MUTED)
        self.set_line_width(.2)
        self.line(mid, y - 2.2, mid, y + 2.2)
        if value is None or value == 0:
            return
        length = abs(value) / maximum * (width / 2 - 1)
        self.set_fill_color(*(ROSE if value < 0 else BLUE))
        self.bar_rect(mid - length if value < 0 else mid, y - 1.3, length, 2.6)

    def bars(self, title, items, *, formatter=percent):
        """Itens (nome, valor). Inclui eixo zero e aceita negativos ou dados ausentes."""
        if not items:
            return
        self.ensure(23)
        self.paragraph(title, size=9, bold=True, color=MUTED, line=4.5, gap=2, align="L")
        maximum = max((abs(v) for _, v in items if v is not None), default=0) or 1
        diverging = any(v is not None and v < 0 for _, v in items)
        label_width = 68
        for i, (name, value) in enumerate(items):
            h = max(9, len(self.lines(name, label_width - 5, size=9.5)) * 4.5 + 4)
            self.ensure(h)
            x, y = self.l_margin, self.get_y()
            self.set_fill_color(*PAPER)
            self.rect(x, y, self.epw, h, style="F")
            self.at(x + 3, y + 2, label_width - 5, name, size=9.5, bold=i == 0, line=4.5)
            bx, bw = x + label_width + 2, self.epw - label_width - 27
            if diverging:
                self.balance_bar(bx, y + h / 2, bw, value, maximum)
            elif value is not None and value != 0:
                self.set_fill_color(*(BLUE if i == 0 else PALE))
                self.bar_rect(bx, y + h / 2 - 1.5, bw * value / maximum, 3)
            self.at(x + self.epw - 24, y + h / 2 - 2.2, 21, formatter(value), size=9.5,
                    bold=True, color=sign_color(value) if diverging else INK, align="R", line=4.5)
            self.set_xy(self.l_margin, y + h)
        self.ln(5)

    def historical_range(self, current, previous, low, high, years, current_label, previous_label):
        if current is None or low is None or high is None:
            return
        self.ensure(47)
        x, y, w = self.l_margin, self.get_y(), self.epw
        self.set_fill_color(*PAPER)
        self.rect(x, y, w, 38, style="F")
        minimum = min(low, current, previous if previous is not None else low, 0)
        maximum = max(high, current, previous if previous is not None else high, 0)
        span = maximum - minimum or 1
        position = lambda v: x + 9 + (v - minimum) / span * (w - 18)
        self.set_fill_color(*PALE)
        self.bar_rect(position(low), y + 17.4, position(high) - position(low), 1.2)
        self.set_draw_color(*MUTED)
        self.set_line_width(.25)
        self.line(position(0), y + 15, position(0), y + 21)
        for v, label, yy, color in ((current, current_label, y + 3, sign_color(current)),
                                     (previous, previous_label, y + 24, BLUE)):
            if v is None:
                continue
            px = position(v)
            self.set_draw_color(*color)
            self.set_fill_color(255, 255, 255)
            self.set_line_width(.6)
            self.ellipse(px - 1.6, y + 16.4, 3.2, 3.2, style="DF")
            label_x = max(x + 2, min(px - 28, x + w - 58))
            self.at(label_x, yy, 56, f"{label}: {signed(v)}", size=9, bold=True, color=color, align="C")
        self.at(x + 3, y + 32, w - 6,
                f"Faixa histórica: mín. {signed(low)}  ·  máx. {signed(high)}", size=8.5, color=MUTED, align="C")
        self.set_xy(x, y + 40)
        period = ", ".join(str(a) for a in years)
        self.source(f"Saldo do mesmo mês nos anos de {period}." if period else "Faixa histórica do mesmo mês.")

    def attention(self, items):
        for i, text in enumerate(items, 1):
            self.ensure(15)
            self.set_fill_color(*PAPER)
            self.font(10.8)
            # Espaços inseparáveis: a justificação não estica o vão entre o número e o texto.
            self.multi_cell(self.epw, 6, f"{i}.\u00a0\u00a0{text}", fill=True, padding=3,
                            align="J", new_x="LMARGIN", new_y="NEXT")
            self.ln(2)

    def highlight(self, text, *, color=NEGATIVE):
        """Aviso destacado: negrito na cor `color` (bordô por padrão), sobre o painel claro."""
        if not text:
            return
        self.font(10.5, bold=True, color=color)
        height = len(self.lines(text, self.epw - 8, size=10.5, bold=True, line=5.6)) * 5.6 + 6
        self.ensure(height + 3)
        y = self.get_y()
        self.set_fill_color(*PAPER)
        self.rect(self.l_margin, y, self.epw, height, style="F")
        self.set_fill_color(*color)
        self.rect(self.l_margin, y, 1.2, height, style="F")
        self.set_xy(self.l_margin + 4, y + 3)
        self.font(10.5, bold=True, color=color)
        self.multi_cell(self.epw - 8, 5.6, text, align="J", new_x="LMARGIN", new_y="NEXT")
        self.set_xy(self.l_margin, y + height + 3)

    def projection_chart(self, historico, projecao, anterior, estoque_mes_anterior, marcos):
        """Estoque observado e projetado (seção Perspectivas, especificação da projeção, seção 9): um
        eixo só; de baixo para cima, faixa provável, projeção da edição anterior (a partir de T-1),
        observado e projeção central; linha vertical em T, ponto em S_T e círculos nos `marcos`
        [(AAAA-MM, valor)]. `historico` e `projecao`: [{competencia, estoque[, estoque_lo, estoque_hi]}]."""
        cores = {"ink": (26, 39, 71), "blue": (58, 95, 168), "prev": (154, 163, 181), "grey": (123, 132, 152),
                 "rule": (217, 222, 231)}
        height = 74
        self.ensure(height + 4)
        x0, y0, w = self.l_margin, self.get_y(), self.epw
        self.set_fill_color(*PAPER)
        self.rect(x0, y0, w, height, style="F")

        def mes(c):
            return int(c[:4]) * 12 + int(c[5:7]) - 1

        meses = [mes(h["competencia"]) for h in historico] + [mes(p["competencia"]) for p in projecao]
        m0, m1 = min(meses), max(meses)
        t = mes(historico[-1]["competencia"])
        s_t = historico[-1]["estoque"]
        prev = sorted((mes(c), v) for c, v in anterior.items() if mes(c) >= t)
        valores = ([h["estoque"] for h in historico] + [p["estoque_lo"] for p in projecao]
                   + [p["estoque_hi"] for p in projecao] + [v for _, v in prev])
        vmin, vmax = min(valores), max(valores)
        bruto = (vmax - vmin) / 4 or 1
        passo = next(p for p in (100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000, 20000, 50000, 100000)
                     if p >= bruto) if bruto <= 100000 else bruto
        lo_axis = (vmin // passo) * passo
        hi_axis = -(-vmax // passo) * passo
        px0, px1 = x0 + 17, x0 + w - 6
        py0, py1 = y0 + 12, y0 + height - 10
        X = lambda m: px0 + (m - m0) / max(m1 - m0, 1) * (px1 - px0)  # noqa: E731
        Y = lambda v: py1 - (v - lo_axis) / (hi_axis - lo_axis) * (py1 - py0)  # noqa: E731

        # legenda numa linha, acima do gráfico
        lx = x0 + 4
        for rotulo, estilo in (("Estoque observado", "obs"), ("Projeção central", "proj"),
                               ("Faixa provável", "faixa"), ("Projeção da edição anterior", "prev")):
            ly = y0 + 5
            if estilo == "faixa":
                with self.local_context(fill_opacity=.16):
                    self.set_fill_color(*cores["blue"])
                    self.rect(lx, ly - 1.6, 5, 3.2, style="F")
            else:
                cor = {"obs": "ink", "proj": "blue", "prev": "prev"}[estilo]
                self.set_draw_color(*cores[cor])
                self.set_line_width(.6)
                self.set_dash_pattern(**({"dash": 1.2, "gap": .8} if estilo == "proj" else
                                         {"dash": .3, "gap": .7} if estilo == "prev" else {}))
                self.line(lx, ly, lx + 5, ly)
                self.set_dash_pattern()
            self.at(lx + 6.5, ly - 2, 60, rotulo, size=7.5, color=MUTED, line=4)
            self.font(7.5)
            lx += 6.5 + self.get_string_width(rotulo) + 6

        # grade horizontal e rótulos do eixo Y (pt-BR)
        v = lo_axis
        while v <= hi_axis + 1e-9:
            self.set_draw_color(*cores["rule"])
            self.set_line_width(.25)
            self.line(px0, Y(v), px1, Y(v))
            self.at(x0, Y(v) - 2, 15, number(v), size=7, color=cores["grey"], align="R", line=4)
            v += passo
        # eixo X: só janeiro e julho
        for m in range(m0, m1 + 1):
            if m % 12 in (0, 6):
                rotulo = f"{['jan', 'jul'][m % 12 // 6]}/{str(m // 12)[2:]}"
                self.at(X(m) - 8, py1 + 2.5, 16, rotulo, size=7, color=cores["grey"], align="C", line=4)

        proj = [(mes(p["competencia"]), p) for p in projecao]
        # 1. faixa provável, partindo de S_T
        pontos = [(X(t), Y(s_t))] + [(X(m), Y(p["estoque_hi"])) for m, p in proj]             + [(X(m), Y(p["estoque_lo"])) for m, p in reversed(proj)]
        with self.local_context(fill_opacity=.16):
            self.set_fill_color(*cores["blue"])
            self.polygon(pontos, style="F")
        # 2. projeção da edição anterior, a partir de T-1
        if prev:
            self.set_draw_color(*cores["prev"])
            self.set_line_width(.5)
            self.set_dash_pattern(dash=.3, gap=.7)
            self.polyline([(X(t - 1), Y(estoque_mes_anterior))] + [(X(m), Y(v)) for m, v in prev])
            self.set_dash_pattern()
        # 3. estoque observado
        self.set_draw_color(*cores["ink"])
        self.set_line_width(.65)
        self.polyline([(X(mes(h["competencia"])), Y(h["estoque"])) for h in historico])
        # 4. projeção central, partindo de S_T
        self.set_draw_color(*cores["blue"])
        self.set_dash_pattern(dash=1.4, gap=.9)
        self.polyline([(X(t), Y(s_t))] + [(X(m), Y(p["estoque"])) for m, p in proj])
        self.set_dash_pattern()
        # marcações: linha em T, ponto em S_T, círculos em dezembro
        self.set_draw_color(*cores["grey"])
        self.set_line_width(.25)
        self.set_dash_pattern(dash=.4, gap=.8)
        self.line(X(t), py0 - 2, X(t), py1)
        self.set_dash_pattern()
        self.at(X(t) + 1, py0 - 2.5, 30, "projeção →", size=7, color=cores["grey"], line=4)
        self.set_fill_color(*cores["ink"])
        self.ellipse(X(t) - 1.1, Y(s_t) - 1.1, 2.2, 2.2, style="F")
        self.at(X(t) - 24, Y(s_t) + 1.5, 23, number(s_t), size=7.5, bold=True, color=cores["ink"], align="R", line=4)
        for competencia, valor in marcos:
            m = mes(competencia)
            self.set_draw_color(*cores["blue"])
            self.set_fill_color(255, 255, 255)
            self.set_line_width(.5)
            self.ellipse(X(m) - 1.3, Y(valor) - 1.3, 2.6, 2.6, style="DF")
            self.at(min(X(m) - 10, px1 - 20), Y(valor) - 6, 20, number(valor), size=7.5, bold=True,
                    color=cores["blue"], align="C", line=4)
        self.set_xy(x0, y0 + height + 3)

    def monthly_series(self, series):
        if not series:
            self.source("Série histórica indisponível para esta competência.")
            return
        self.ensure(64)
        x, y, w = self.l_margin, self.get_y(), self.epw
        self.set_fill_color(*PAPER)
        self.rect(x, y, w, 57, style="F")
        maximum = max(abs(s["saldo_liquido"]) for s in series) or 1
        step = (w - 8) / len(series)
        axis = y + 26
        self.rule(axis, MUTED, .2, x + 4, w - 8)
        for i, s in enumerate(series):
            value = s["saldo_liquido"]
            h = abs(value) / maximum * 17
            bx = x + 4 + i * step + step * .22
            provisional = s.get("situacao") == "provisório"
            color = (ROSE if provisional else NEGATIVE) if value < 0 else (ACCENT if provisional else BLUE)
            self.set_fill_color(*color)
            self.bar_rect(bx, axis - h if value >= 0 else axis, step * .56, h)
            self.at(bx - step * .22, axis - h - 5 if value >= 0 else axis + h + .5,
                    step, signed(value), size=7, color=sign_color(value), align="C")
            c = s["competencia"]
            self.at(bx - step * .22, y + 49, step, f"{c[4:]}/{c[2:4]}", size=7, color=MUTED, align="C")
        self.set_xy(x, y + 60)
