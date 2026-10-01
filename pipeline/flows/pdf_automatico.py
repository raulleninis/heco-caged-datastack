"""Apresentação do boletim automático, mantendo os indicadores e notas do mart."""
from pdf_design import BoletimPDF, BLUE, MUTED, Identidade, number, percent, signed, money, sign_color


def renderizar(b, destino, *, resumo, notas, nome_competencia, competencia_deslocada, identidade=Identidade()):
    mes = nome_competencia(b.competencia)
    onde = f" em {identidade.territorio}" if identidade.territorio else ""
    title = f"Evolução do emprego formal{onde} · {mes}"
    pdf = BoletimPDF(title, identidade=identidade, status=b.situacao if b.reconciliado else "só-MOV")
    pdf.cover(title, resumo[0])
    t, estoque = b.total, b.estoque_total
    ano_anterior = competencia_deslocada(b.competencia, -12)
    ref = b.total_de(ano_anterior)

    def comparison(key):
        if ref is None:
            return "Comparação anual indisponível"
        return f"{nome_competencia(ano_anterior)}: {number(ref[key])} ({signed(t[key] - ref[key])})"

    taxa = estoque.get("taxa_variacao_mensal") if estoque else None
    cards = [
        ("Saldo do mês", signed(t["saldo_liquido"]),
         f"taxa mensal de {percent(taxa * 100)}" if taxa is not None else "vínculos formais", sign_color(t["saldo_liquido"])),
        ("Admissões", number(t["admissoes"]), comparison("admissoes"), BLUE),
        ("Desligamentos", number(t["desligamentos"]), comparison("desligamentos"), BLUE),
    ]
    if estoque:
        cards.append(("Estoque", number(estoque["estoque"]), "estimativa · vínculos formais", BLUE))
    pdf.cards(cards)
    situacao = f"Dados {b.situacao}s." if b.reconciliado else "Somente movimentações declaradas no prazo (MOV)."
    pdf.source(f"Fonte: Novo CAGED, Ministério do Trabalho e Emprego. {situacao}")
    pdf.section("Panorama")
    for text in resumo[1:]:
        pdf.paragraph(text, size=10.5, line=5.6, gap=2)
    pdf.section("Evolução mensal", reserve=64)
    pdf.monthly_series(b.serie)
    pdf.source(f"Saldo líquido nos últimos {len(b.serie)} meses disponíveis. "
               + ("Barras claras: dados provisórios; escuras: consolidados." if b.reconciliado else "Base: CAGEDMOV."))

    pdf.add_page()
    pdf.section("Setores")
    values = [row["saldo_liquido"] for row in b.linhas]
    headers = ["Grupamento", "Saldo", "Perda | ganho", "Admissões", "Deslig."]
    widths = [43, 18, 29, 27, 27]
    if estoque:
        headers += ["Estoque*", "Var. mês*"]
        widths = [39, 16, 28, 24, 22, 25, 26]
    rows = []
    colors = {}
    for i, row in enumerate(b.linhas):
        cells = [row["grupamento"], signed(row["saldo_liquido"]), "", number(row["admissoes"]), number(row["desligamentos"])]
        if estoque:
            rate = row.get("taxa_variacao_mensal")
            cells += [number(row.get("estoque")), percent(rate * 100 if rate is not None else None)]
        rows.append(cells)
        colors[i, 1] = sign_color(row["saldo_liquido"])
    total = ["Total", signed(t["saldo_liquido"]), "", number(t["admissoes"]), number(t["desligamentos"])]
    if estoque:
        total += [number(estoque["estoque"]), percent(taxa * 100 if taxa is not None else None)]
    colors[len(rows), 1] = sign_color(t["saldo_liquido"])
    rows.append(total)
    # O total é numérico; a escala das barras compara apenas os grupamentos.
    pdf.table(headers, rows, widths, bar_column=2, bar_values=values + [None], highlights=[len(rows) - 1], colors=colors)
    pdf.source("Barras proporcionais ao saldo; eixo central = zero." +
               (" * Estoque e variação: estimativas a partir do estoque de referência do MTE (ver notas)." if estoque else ""))

    pdf.section("Remuneração na admissão")
    pdf.table(["Grupamento", "Salário mediano", "Salário médio", "Índice de Palma"],
              [[r["grupamento"], money(r.get("salario_mediano_admissao")), money(r.get("salario_medio_admissao")),
                number(r.get("palma_index_admissao"), 2)] for r in b.linhas], [54, 44, 44, 38])
    pdf.source("Salários das admissões declaradas no prazo, com valor mensal válido. Mediana como referência; média para comparação.")
    notes_height = 20 + sum(len(pdf.lines(note, pdf.epw, size=9)) * 4.6 + 2 for note in notas)
    # Quando couberem numa página, as notas começam juntas; notas maiores continuam normalmente.
    if notes_height <= pdf.page_break_trigger - 34:
        pdf.ensure(notes_height)
    pdf.section("Nota metodológica", numbered=False)
    for note in notas:
        pdf.paragraph(note, size=9, line=4.6, color=MUTED, gap=2)
    pdf.output(str(destino))
