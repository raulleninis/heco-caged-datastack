"""Apresentação do boletim com IA, independente das etapas de revisão e envio."""
import json
from pathlib import Path

from pdf_design import BoletimPDF, BLUE, INK, MUTED, carregar_identidade, fact, money, number, percent, sign_color, signed


def gerar_pdf(pasta: Path, *, destino: Path | None = None, aviso_ia: str) -> Path:
    resultado = json.loads((pasta / "resultado.json").read_text(encoding="utf-8"))
    fatos = json.loads((pasta / "fatos.json").read_text(encoding="utf-8"))
    if str(resultado["competencia"]) != str(fatos["competencia"]):
        raise ValueError("Resultado e fatos pertencem a competências diferentes.")
    destino = destino or pasta / f"boletim-ia-{resultado['competencia']}.pdf"
    renderizar(resultado, fatos, destino, aviso_ia=aviso_ia)
    return destino


def renderizar(resultado, fatos, destino, *, aviso_ia):
    b = resultado["boletim"]
    p = fatos["panorama"]
    rotulos = fatos.get("rotulos", {})
    mes = rotulos.get("competencia", str(fatos["competencia"]))
    anterior = rotulos.get("ano_anterior", "mesmo mês do ano anterior")
    status = "provisório" if fatos.get("provisorio", True) else "consolidado"
    pdf = BoletimPDF(b["titulo"], identidade=carregar_identidade(str(fatos["territorio"]["codigo"])), status=status)
    pdf.cover(b["titulo"], b["sintese"])
    referencia = p.get("mesmo_mes_ano_anterior") or {}

    def comparison(key):
        now, before = fact(p, key), fact(referencia, key)
        if before is None:
            return "Comparação anual indisponível"
        delta = f" ({signed(now - before)})" if now is not None else ""
        return f"{anterior}: {number(before)}{delta}"

    pdf.cards([
        ("Saldo do mês", signed(fact(p, "saldo")), f"taxa mensal de {percent(fact(p, 'taxa_mes'))}", sign_color(fact(p, "saldo"))),
        ("Admissões", number(fact(p, "admissoes")), comparison("admissoes"), BLUE),
        ("Desligamentos", number(fact(p, "desligamentos")), comparison("desligamentos"), BLUE),
        ("Estoque", number(fact(p, "estoque")), "vínculos formais", BLUE),
    ])
    pdf.source(f"Fonte: Novo CAGED, Ministério do Trabalho e Emprego. Dados {status}s.")
    pdf.section("Panorama")
    panorama = b.get("panorama", [])
    if panorama:
        pdf.paragraph(panorama[0])
    faixa = p.get("sazonalidade") or {}
    pdf.historical_range(fact(p, "saldo"), fact(referencia, "saldo"), fact(faixa, "minimo"),
                         fact(faixa, "maximo"), faixa.get("anos", []), mes, anterior)
    for text in panorama[1:]:
        pdf.paragraph(text)

    pdf.add_page()
    pdf.section("Setores")
    for text in b.get("setores", []):
        pdf.paragraph(text)
    grupos = fatos.get("setorial", {}).get("grupamentos", {})
    destaques = fatos.get("setorial", {}).get("destaques", [])
    rows, values, highlights, colors = [], [], [], {}
    for i, (name, item) in enumerate(grupos.items()):
        value = fact(item, "saldo")
        rows.append([name, signed(value), "", number(fact(item, "admissoes")),
                     number(fact(item, "desligamentos")), number(fact(item, "estoque")), percent(fact(item, "taxa_mes"))])
        values.append(value)
        colors[i, 1] = sign_color(value)
        if name in destaques:
            highlights.append(i)
    if rows:
        pdf.table(["Grupamento", "Saldo", "Perda | ganho", "Admissões", "Deslig.", "Estoque", "Var. mês"],
                  rows, [39, 16, 30, 24, 22, 25, 24], bar_column=2, bar_values=values,
                  highlights=highlights, colors=colors)
        pdf.source(f"Grupamentos de atividade econômica, {mes}. Barras proporcionais ao saldo; eixo central = zero.")
    for item in fatos.get("desagregacao", []):
        pdf.ensure(65)
        pdf.rule(pdf.get_y(), INK, .7)
        pdf.ln(4)
        pdf.paragraph(f"{item.get('nivel', 'Detalhamento').upper()} · {item['grupamento']}",
                      size=8.5, bold=True, color=MUTED, line=4, gap=2)
        pdf.paragraph(item["nome"], size=12, bold=True, line=5.8)
        value = fact(item, "saldo")
        pdf.cards([
            ("Saldo", signed(value), f"vínculos em {mes}", sign_color(value)),
            ("Admissões", number(fact(item, "admissoes")), "no mês", BLUE),
            ("Desligamentos", number(fact(item, "desligamentos")), "no mês", BLUE),
        ])
        previous = fact(item, "saldo_ano_anterior")
        if previous is not None:
            pdf.source(f"Saldo em {anterior}: {signed(previous)} vínculos.")
        pdf.bars(f"Composição do saldo em {item['grupamento']}", [
            ("Atividade em destaque", value),
            (f"Restante de {item['grupamento']}", fact(item, "saldo_restante_do_grupamento")),
            (f"{item['grupamento']} (total)", fact(grupos.get(item["grupamento"], {}), "saldo")),
        ], formatter=signed)

    pdf.add_page()
    pdf.section("Contexto regional")
    for text in b.get("contexto_regional", []):
        pdf.paragraph(text)
    c = fatos.get("comparacao", {})
    regions = [x for x in [c.get("territorio"), *c.get("regioes", []), c.get("uf"), c.get("brasil")] if x]
    if regions:
        pdf.bars("VARIAÇÃO DO ESTOQUE EM 12 MESES", [(x["nome"], fact(x, "taxa_12_meses")) for x in regions])
        pdf.table(["Território", "Saldo", "Estoque", "Var. mês", "Var. 12 meses"],
                  [[x["nome"], signed(fact(x, "saldo")), number(fact(x, "estoque")),
                    percent(fact(x, "taxa_mes")), percent(fact(x, "taxa_12_meses"))] for x in regions],
                  [65, 25, 30, 26, 34], highlights=[0] if c.get("territorio") else [])
        pdf.source(f"Comparação regional, {mes}.")

    pdf.section("Perfil e remuneração", reserve=45)
    perfil = fatos.get("perfil", {})
    sexo = perfil.get("sexo", {})
    homem, mulher = sexo.get("Homem", {}), sexo.get("Mulher", {})
    jovem = perfil.get("faixa_etaria", {}).get("18 a 24", {})
    salario = fatos.get("salario", {})
    cards = []
    if homem and mulher and not any(x.get("base_pequena") for x in (homem, mulher)):
        cards.append(("Admissões por sexo", percent(fact(homem, "participacao_admissoes")),
                      f"homens · {percent(fact(mulher, 'participacao_admissoes'))} mulheres", BLUE))
    if jovem and not jovem.get("base_pequena"):
        cards.append(("18 a 24 anos", percent(fact(jovem, "participacao_admissoes")),
                      f"das admissões; {percent(fact(jovem, 'participacao_admissoes_ano_anterior'))} em {anterior}", BLUE))
    if salario and not salario.get("base_pequena"):
        cards.append(("Salário mediano de admissão", money(fact(salario, "mediana")),
                      f"variação nominal de {percent(fact(salario, 'variacao_nominal_mediana'))} frente a {anterior}", BLUE))
    if cards:
        pdf.cards(cards)
    for text in b.get("perfil_e_remuneracao", []):
        pdf.paragraph(text)

    pix = (fatos.get("indicadores_externos") or {}).get("pix")
    if b.get("pontos_de_atencao") or pix:
        pdf.add_page()
    if b.get("pontos_de_atencao"):
        pdf.section("Pontos de atenção")
        pdf.attention(b["pontos_de_atencao"])
    if pix:
        pdf.section("Pix por município")
        pdf.source(f"Banco Central · {pix['competencia']} · comparação com {pix['comparado_com']}")
        recortes = pix.get("recortes", [])
        pdf.bars("EMPRESAS RECEBEDORAS DE PIX · VARIAÇÃO NO PERÍODO",
                 [(x["nome"], fact(x, "variacao_empresas_12m")) for x in recortes])
        pdf.table(["Território", "Empresas", "Var. empresas", "R$ milhões", "Var. nominal"],
                  [[x["nome"], number(fact(x, "empresas_recebedoras")), percent(fact(x, "variacao_empresas_12m")),
                    number(fact(x, "valor_recebido_milhoes"), 1), percent(fact(x, "variacao_valor_12m"))] for x in recortes],
                  [64, 26, 30, 30, 30], highlights=[0])
        pdf.source(pix.get("cuidados", "Valores nominais."))
    pdf.section("Nota metodológica", numbered=False)
    pdf.paragraph(b["nota_metodologica"], size=9.3, line=4.8, color=MUTED)
    pdf.paragraph(aviso_ia, size=9.3, line=4.8, color=MUTED)
    pdf.output(str(destino))
