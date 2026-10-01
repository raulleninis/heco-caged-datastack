"""Apresentação do boletim com IA, independente das etapas de revisão e envio."""
import json
from pathlib import Path

from pdf_design import BoletimPDF, BLUE, MUTED, carregar_identidade, fact, money, number, percent, sign_color, signed


def gerar_pdf(pasta: Path, *, destino: Path | None = None, aviso_ia: str) -> Path:
    resultado = json.loads((pasta / "resultado.json").read_text(encoding="utf-8"))
    fatos = json.loads((pasta / "fatos.json").read_text(encoding="utf-8"))
    if str(resultado["competencia"]) != str(fatos["competencia"]):
        raise ValueError("Resultado e fatos pertencem a competências diferentes.")
    destino = destino or pasta / f"boletim-ia-{resultado['competencia']}.pdf"
    renderizar(resultado, fatos, destino, aviso_ia=aviso_ia)
    return destino


def ordenar_grupamentos(grupos: dict) -> list[tuple[str, dict]]:
    """Ordem alfabética, com "Não Identificado" sempre por último."""
    return sorted(grupos.items(), key=lambda kv: (kv[0] == "Não Identificado", kv[0]))


def _perspectivas(pdf, projecao: dict) -> None:
    """Seção Perspectivas (F21), na ordem da especificação: parágrafo, três indicadores, gráfico,
    legenda, o aviso de projeção experimental em destaque e a revisão frente à edição anterior.
    Textos fixos, gerados por código (projecao.redigir_texto)."""
    texto, k = projecao["texto"], projecao["kpis"]
    ano, prox = projecao["ano"], projecao["ano_prox"]
    pdf.section("Perspectivas", reserve=70)
    pdf.paragraph(texto["paragrafo"])

    def faixa(par, fmt):
        return f"faixa: {fmt(round(par[0]))} a {fmt(round(par[1]))}"

    saldo = round(k["saldo_ano"])
    pdf.cards([
        (f"Estoque projetado · dez/{ano}", number(round(k["estoque_dez_ano"])),
         faixa(k["estoque_dez_ano_faixa"], number), BLUE),
        (f"Saldo projetado em {ano}", signed(saldo), faixa(k["saldo_ano_faixa"], signed), BLUE),
        (f"Estoque projetado · dez/{prox}", number(round(k["estoque_dez_prox"])),
         faixa(k["estoque_dez_prox_faixa"], number), BLUE),
    ])
    pdf.projection_chart(projecao["historico"], projecao["projecao_mensal"], projecao["serie_anterior"],
                         projecao["estoque_mes_anterior"],
                         [(f"{ano}-12", round(k["estoque_dez_ano"])), (f"{prox}-12", round(k["estoque_dez_prox"]))])
    pdf.source(texto["legenda"])
    pdf.highlight(texto["aviso_experimental"])
    if texto.get("revisao"):
        pdf.paragraph(f"**Revisão.** {texto['revisao']}", size=10.5, line=5.8, markdown=True)


def _mes_curto(rotulo: str) -> str:
    """'setembro de 2026' -> 'set/26'."""
    partes = rotulo.split()
    return f"{partes[0][:3]}/{partes[-1][-2:]}" if len(partes) >= 3 else rotulo


def _nome_atividade(item: dict) -> str:
    """Nome da atividade, sem caixa alta (as divisões CNAE vêm em maiúsculas do IBGE)."""
    nome = item["nome"]
    return nome.capitalize() if nome.isupper() else nome


def renderizar(resultado, fatos, destino, *, aviso_ia):
    """Partes (revisões de 01/10/2026): 1) síntese, cards e panorama; 2) setores com a tabela de
    grupamentos e a das atividades em destaque; 3) contexto regional, perfil e remuneração; 4)
    perspectivas (projeção, F21), sinais da atividade (Pix), pontos de atenção e nota
    metodológica. Numeração das seções pela ordem: 05 Perspectivas, 06 Pix, 07 Pontos de atenção."""
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
    for text in b.get("panorama", []):
        pdf.paragraph(text)
    # A faixa histórica é referência complementar: o gráfico vem depois da interpretação.
    faixa = p.get("sazonalidade") or {}
    pdf.historical_range(fact(p, "saldo"), fact(referencia, "saldo"), fact(faixa, "minimo"),
                         fact(faixa, "maximo"), faixa.get("anos", []), mes, anterior)

    pdf.add_page()
    pdf.section("Setores")
    for text in b.get("setores", []):
        pdf.paragraph(text)
    grupos = fatos.get("setorial", {}).get("grupamentos", {})
    destaques = fatos.get("setorial", {}).get("destaques", [])
    rows, values, highlights, colors = [], [], [], {}
    for i, (name, item) in enumerate(ordenar_grupamentos(grupos)):
        value = fact(item, "saldo")
        rows.append([name, signed(value), "", number(fact(item, "admissoes")),
                     number(fact(item, "desligamentos")), number(fact(item, "estoque")), percent(fact(item, "taxa_mes"))])
        values.append(value)
        colors[i, 1] = sign_color(value)
        if name in destaques:
            highlights.append(i)
    if rows:
        # Total do município: os números do panorama (os mesmos dos cards da página 1). A barra fica
        # vazia: a escala compara só os grupamentos.
        total = fact(p, "saldo")
        colors[len(rows), 1] = sign_color(total)
        rows.append(["Total", signed(total), "", number(fact(p, "admissoes")), number(fact(p, "desligamentos")),
                     number(fact(p, "estoque")), percent(fact(p, "taxa_mes"))])
        pdf.table(["Grupamento", "Saldo", "Perda | ganho", "Admissões", "Deslig.", "Estoque", "Var. mês"],
                  rows, [39, 16, 30, 24, 22, 25, 24], bar_column=2, bar_values=values + [None],
                  highlights=highlights, colors=colors, bold=[len(rows) - 1])
        pdf.source(f"Grupamentos de atividade econômica, {mes}. Barras proporcionais ao saldo; eixo central = zero.")
    # Uma tabela só para as atividades em destaque, em vez de um bloco de cards e barras por
    # atividade (revisão de 01/10/2026: a antiga página 3 repetia o texto da página 2).
    atividades = fatos.get("desagregacao", [])
    if atividades:
        rows, colors = [], {}
        for i, item in enumerate(atividades):
            linha = [f"{_nome_atividade(item)} ({item['grupamento']})", fact(item, "saldo"),
                     fact(item, "admissoes"), fact(item, "desligamentos"),
                     fact(item, "saldo_ano_anterior"), fact(item, "saldo_restante_do_grupamento")]
            for column in (1, 4, 5):
                colors[i, column] = sign_color(linha[column])
            rows.append([linha[0], signed(linha[1]), number(linha[2]), number(linha[3]),
                         signed(linha[4]), signed(linha[5])])
        pdf.table(["Atividade em destaque (grupamento)", "Saldo", "Admissões", "Deslig.",
                   f"Saldo em {anterior}", "Demais atividades do grupamento"],
                  rows, [66, 16, 21, 18, 25, 28], colors=colors)
        pdf.source(f"Atividades que mais explicam o saldo dos grupamentos em destaque, {mes}. "
                   "Demais atividades: saldo do restante do grupamento.")

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
    salario = fatos.get("salario", {})
    cards = []
    if homem and mulher and not any(x.get("base_pequena") for x in (homem, mulher)):
        cards.append(("Admissões por sexo", percent(fact(homem, "participacao_admissoes")),
                      f"homens · {percent(fact(mulher, 'participacao_admissoes'))} mulheres", BLUE))
    if salario and not salario.get("base_pequena"):
        cards.append(("Salário mediano de admissão", money(fact(salario, "mediana")),
                      f"variação nominal de {percent(fact(salario, 'variacao_nominal_mediana'))} frente a "
                      f"{anterior}, sem correção pela inflação", BLUE))
    if cards:
        pdf.cards(cards)
    for text in b.get("perfil_e_remuneracao", []):
        pdf.paragraph(text)

    projecao = fatos.get("projecao")
    if projecao:
        _perspectivas(pdf, projecao)

    pix = (fatos.get("indicadores_externos") or {}).get("pix")
    sinais = b.get("sinais_da_atividade", [])
    if pix:
        # Sem quebra forçada: o Pix segue o perfil e a parte final cabe na página 4. Com texto, é
        # uma seção de sinais da atividade; sem, só o quadro complementar.
        pdf.section("Sinais da atividade econômica: Pix" if sinais else "Indicador complementar: Pix", reserve=40)
        for text in sinais:
            pdf.paragraph(text)
        recortes = pix.get("recortes", [])
        # Uma tabela só: território nas linhas; o nível do mês do CAGED e a trajetória da variação
        # do valor recebido (meses anteriores, o do CAGED e os posteriores já publicados, com *).
        meses = ([(m, False) for m in pix.get("anteriores") or []] + [(pix, False)]
                 + [(m, True) for m in pix.get("posteriores") or []])

        def valor(mes, nome):
            return next((fact(x, "variacao_valor_12m") for x in mes["recortes"] if x["nome"] == nome), None)

        cabecalho = [f"Valor {_mes_curto(m['competencia'])}{'*' if depois else ''}" for m, depois in meses]
        pdf.table(["Território", "R$ milhões", "Var. empresas", *cabecalho],
                  [[x["nome"], number(fact(x, "valor_recebido_milhoes"), 1), percent(fact(x, "variacao_empresas_12m")),
                    *[percent(valor(m, x["nome"])) for m, _ in meses]] for x in recortes],
                  [50, 20, 20, *[17] * len(meses)], highlights=[0])
        mes_caged = _mes_curto(pix["competencia"])
        pdf.source(f"Fonte: Banco Central, Pix por município. R$ milhões e empresas: {pix['competencia']}. Variações "
                   f"nominais frente ao mesmo mês do ano anterior; {mes_caged} é o mês do CAGED"
                   + ("; * mês publicado depois dele, sinal a acompanhar, não previsão" if pix.get("posteriores") else "")
                   + ". Indicador complementar de atividade, não de emprego: parte da alta é adoção do Pix, por isso "
                   "a leitura é relativa. Município do cadastro da conta.")
    if b.get("pontos_de_atencao"):
        pdf.section("Pontos de atenção")
        pdf.attention(b["pontos_de_atencao"])
    pdf.section("Nota metodológica", numbered=False)
    pdf.paragraph(b["nota_metodologica"], size=9.3, line=4.8, color=MUTED)
    if projecao:
        pdf.paragraph(projecao["texto"]["nota_metodologica"], size=9.3, line=4.8, color=MUTED)
        pdf.paragraph(projecao["texto"]["fragilidades"], size=9.3, line=4.8, color=MUTED)
    pdf.paragraph(aviso_ia, size=9.3, line=4.8, color=MUTED)
    pdf.output(str(destino))
