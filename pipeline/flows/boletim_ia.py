"""
Boletim com IA (F19 parte 3, revista na 3b-1): analista → redator → revisor, sobre os fatos da
parte 1, dentro das proteções da parte 2. Resultado fica AGUARDANDO APROVAÇÃO humana; nada é
enviado aqui.

Fluxo fixo, sem agente decidindo chamar outro (docs/fatias/F19-boletim-com-ia.md):

1. fatos (flows/fatos.py), com hash. Mesmo hash e resultado já gerado: reaproveita, sem LLM
   (só gera de novo com --refazer).
2. analista: escolhe até 5 destaques, citando ids de `numeros`.
3. redator: escreve o texto na estrutura do roteiro (síntese, panorama, setores, contexto
   regional, perfil e remuneração, pontos de atenção, nota metodológica). O verificador de
   números é o seu output_validator: número fora dos fatos gera UMA nova tentativa; na última,
   o texto é aceito e segue com o relatório para a revisão humana (em vez de abortar e perder o
   que foi pago). As rejeições de cada tentativa ficam registradas.
4. revisor (outra família de modelo, com os fatos COMPLETOS e os avisos de estilo): parecer
   sobre causalidade, fontes, rótulos, identificação e estilo. Problema grave gera uma segunda
   versão do redator, verificada de novo.
5. grava fatos.json, resultado.json e boletim.md. As TABELAS do boletim.md são geradas por
   código a partir dos fatos (dois níveis: o texto interpreta, a tabela detalha); o LLM nunca
   monta tabela.

Pior caso de requisições: analista 2 + redator 2 + revisor 1 + redator 2 = 7, dentro do
request_limit de 8 da Execucao. Hipóteses ficam fora até existirem evidências externas (parte 4).

Uso:
    python flows/boletim_ia.py 280480 202607 [--refazer] [--warehouse ...]
"""

import argparse
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext

import fatos as fatos_mod
import ia
from verificador import _decimal, avisos_de_estilo, formatar_milhares, rotulos_dos_fatos, verificar_texto

# Avisos de estilo que, sozinhos, justificam uma segunda versão do redator (~US$ 0,02).
AVISOS_PARA_NOVA_VERSAO = 3

e_modelo_de_decisao = ia.e_modelo_de_decisao  # modelos de decisão (Jev) não redigem


# --- saídas tipadas ---------------------------------------------------------------------------


class Destaque(BaseModel):
    tema: str
    ids: list[str] = Field(min_length=1, description="ids da tabela `numeros` que sustentam o destaque")
    por_que: str = Field(description="qual regra ou gatilho o torna destaque")


class PerguntaParaEvidencia(BaseModel):
    """Para o pesquisador (parte 4): o que uma evidência externa poderia esclarecer."""
    tema: str
    pergunta: str
    escala: Literal["municipal", "regional", "estadual", "nacional"]


class Duvida(BaseModel):
    """3b-2: o que o analista não consegue decidir só com os fatos."""
    pergunta: str
    tipo: Literal["fato_local", "metodo"] = Field(description="fato_local: depende de conhecimento sobre o "
                                                   "município que os dados não trazem; metodo: de como ler os dados")
    ids: list[str] = Field(default_factory=list, description="ids de `numeros` relacionados")
    por_que: str


class Analise(BaseModel):
    destaques: list[Destaque] = Field(max_length=5)
    desagregacoes: list[str] = Field(default_factory=list, description="códigos de `desagregacao` a usar no texto")
    perguntas_para_evidencias: list[PerguntaParaEvidencia] = Field(default_factory=list, max_length=3)
    duvidas: list[Duvida] = Field(default_factory=list, max_length=3,
                                  description="só dúvidas que mudariam o texto; na dúvida, prefira não afirmar")


class Orientacao(BaseModel):
    """Resposta do advisor a uma dúvida de método."""
    resposta: str = Field(description="até 5 frases, sem números novos")
    confianca: Literal["alta", "media", "baixa"]


class Afirmacao(BaseModel):
    texto: str = Field(description="a afirmação interpretativa, como está no boletim")
    ids: list[str] = Field(min_length=1, description="ids de `numeros` que a sustentam")


class Boletim(BaseModel):
    titulo: str
    sintese: str = Field(description="até 3 frases: o que aconteceu, onde se concentrou, o estoque")
    panorama: list[str] = Field(description="parágrafos: mês, comparação com o mesmo mês do ano anterior, acumulado no ano, 12 meses")
    setores: list[str] = Field(description="parágrafos: o destaque em detalhe; os demais numa frase")
    contexto_regional: list[str] = Field(description="parágrafos: taxas do município, da região e da UF")
    perfil_e_remuneracao: list[str] = Field(description="parágrafos: só as categorias relevantes; salário mediano")
    pontos_de_atencao: list[str] = Field(max_length=4, description="indicadores a acompanhar nos próximos meses")
    nota_metodologica: str = Field(description="provisoriedade, faixa histórica, bases pequenas, sem identificação, base do salário")
    afirmacoes: list[Afirmacao] = Field(default_factory=list, max_length=10,
                                        description="as afirmações interpretativas do texto (comparações, posição na "
                                                    "faixa histórica, concentração, direção), cada uma com seus ids")

    def secoes(self) -> list[tuple[str, list[str]]]:
        return [("Panorama", self.panorama), ("Setores", self.setores),
                ("Contexto regional", self.contexto_regional), ("Perfil e remuneração", self.perfil_e_remuneracao)]

    def texto(self) -> str:
        partes = [self.titulo, self.sintese]
        for _, paragrafos in self.secoes():
            partes += paragrafos
        return "\n".join(partes + self.pontos_de_atencao + [self.nota_metodologica])

    def com_milhares(self) -> "Boletim":
        """Mesmo texto com separador de milhar (formatação por código, valor inalterado)."""
        f = formatar_milhares
        return self.model_copy(update={
            "titulo": f(self.titulo), "sintese": f(self.sintese), "panorama": [f(x) for x in self.panorama],
            "setores": [f(x) for x in self.setores], "contexto_regional": [f(x) for x in self.contexto_regional],
            "perfil_e_remuneracao": [f(x) for x in self.perfil_e_remuneracao],
            "pontos_de_atencao": [f(x) for x in self.pontos_de_atencao], "nota_metodologica": f(self.nota_metodologica)})


class Problema(BaseModel):
    tipo: Literal["numero", "causalidade", "fonte", "rotulo", "identificacao", "estilo", "estrutura"]
    gravidade: Literal["grave", "menor"]
    trecho: str
    sugestao: str


class Parecer(BaseModel):
    problemas: list[Problema] = Field(default_factory=list)
    resumo: str


@dataclass
class Contexto:
    """deps dos agentes: a tabela de números, os rótulos aceitos e o registro das rejeições.
    Números citados nas evidências (notícias) entram na verificação como unidade "fonte"."""
    fatos: dict
    evidencias: list[dict] = field(default_factory=list)
    rejeicoes: list[list[str]] = field(default_factory=list)

    @property
    def numeros(self) -> dict:
        extras = {}
        for i, e in enumerate(self.evidencias):
            for j, bruto in enumerate(e.get("numeros", [])):
                valor = _decimal(str(bruto).strip().rstrip("%"))
                if valor is not None:
                    extras[f"evidencia.{i}.{j}"] = {"valor": str(valor), "unidade": "fonte", "descricao": e["fonte"]}
        return {**self.fatos["numeros"], **extras}

    @property
    def rotulos(self) -> list[str]:
        return rotulos_dos_fatos(self.fatos)


# --- instruções (resumo de docs/boletim-ia/roteiro.md e da revisão editorial de 29/09/2026) ---

REGRAS = """\
Regras obrigatórias:
- Todo número tem de estar na tabela `numeros` dos fatos, com o mesmo valor. NUNCA calcule,
  some, subtraia ou derive números, nem diferenças de percentuais. Se o número que você quer
  não está na tabela, não o use. Campos dentro de `apoio` não são publicáveis.
- Unidade de análise: o município. Região e UF são contexto, não explicação.
- Análise setorial pelos grandes grupamentos; desagregue só as atividades de `desagregacao`
  (use `nome_curto` na síntese, `nome` na seção de setores). Nunca identifique ou insinue
  empresas ou estabelecimentos.
- Não atribua causa. Descreva o que os dados mostram. Não há hipóteses nesta versão: não
  especule sobre motivos.
- Salário: a mediana é a referência. A comparação com o ano anterior é NOMINAL (sem correção
  pela inflação): diga isso. A média não precisa aparecer.
- Categorias com `base_pequena` ou `sem_identificacao` não são interpretadas; vão para a nota.
- Indicadores externos (`indicadores_externos`), quando houver:
  - Pix por município: aproximação da atividade das empresas locais, NUNCA do emprego. Leitura
    sempre RELATIVA (município contra região e estado; `diferenca_empresas_vs_uf_pp`), porque o
    Pix ainda cresce por adoção. Valores nominais. Cite a fonte (Banco Central) e diga que é
    aproximação. Os cuidados vão para a nota metodológica;
  - Selic: só como contexto para os setores sensíveis a crédito em destaque; nunca como causa.
- Evidências externas (notícias), quando houver, SEMPRE com fonte e data no texto:
  - janela "recente": só como algo a acompanhar nos pontos de atenção ("segundo o g1, em 25 de
    setembro, ..."). Nunca como explicação do mês do boletim, que é anterior;
  - janela "competencia" com `apoia_hipotese` = true: pode virar UMA hipótese nos pontos de
    atenção, começando por "Hipótese:", sem quantificar efeito sobre o saldo;
  - demais evidências: não use no texto (ficam nas leituras relacionadas).
  Números de uma notícia só com a atribuição ("segundo a Infonet, 300 vagas").
"""

EDITORIAL = """\
Estilo e estrutura (leitor: gestor público; objetivo: entender rápido o que aconteceu, onde se
concentrou, como se compara e o que acompanhar):
- Síntese: no máximo 3 frases. O resultado do mês, onde a perda ou o ganho se concentrou, o
  estoque. Não repita a síntese no panorama.
- Panorama, nesta ordem: o mês; o mesmo mês do ano anterior (pelo nome, ex.: "julho de 2025",
  do campo `rotulos`) e o que mudou em admissões e desligamentos; o acumulado no ano; o
  acumulado em 12 meses. Se ano e 12 meses tiverem sinais opostos, explique que medem
  períodos diferentes.
- Setores: o destaque em detalhe; os demais grupamentos numa única frase, usando
  `fora_dos_destaques`. Não comente grupamento sem movimento. A tabela completa é gerada à
  parte, não a reproduza.
- Faixa histórica: ao citá-la, diga o critério (mínimo e máximo do mesmo mês nos anos de `anos`).
- Contexto regional: compare TAXAS (mês e 12 meses); o município faz parte da região e da UF.
- Perfil: comente só categorias com `relevante` = true.
- Pontos de atenção: 2 a 4 indicadores para acompanhar nos próximos meses, sem especular causas.
- Nota metodológica: um único parágrafo com a provisoriedade (a ÚNICA menção a ela), o
  critério da faixa histórica, as categorias sem identificação e a base do salário.
- Convenções: no texto, "perda de 83 vínculos" ou "saldo negativo de 83", sem sinal de menos;
  percentuais SEMPRE com 2 casas decimais (0,33%); "vínculos" para tudo (não alterne com
  postos, vagas, empregos). Títulos só com a primeira letra maiúscula.
- Frases diretas ("teve", "foi", "caiu"). Sem travessão. Sem gerúndio decorativo
  ("destacando-se", "evidenciando"). Sem "vale ressaltar", "no tocante", "cenário",
  "impulsionado". Não repita um mesmo número em duas seções.
"""

INSTRUCOES = {
    "analista": "Você é o analista de um boletim mensal de emprego formal (Novo CAGED). Recebe os fatos já "
                "calculados e escolhe o que merece destaque, seguindo os `gatilhos` e os `destaques` setoriais. "
                "Cada destaque cita ids da tabela `numeros`. Pode sugerir até 3 perguntas que uma evidência "
                "externa (notícia, indicador oficial) ajudaria a esclarecer. Dúvidas (`duvidas`): só as que "
                "mudariam o texto; NUNCA sobre empresas ou estabelecimentos, nem 'um ou poucos "
                "estabelecimentos' (vira identificação): formule no nível do setor ou do município.\n" + REGRAS,
    "redator": "Você redige, em português do Brasil, o texto de um boletim mensal de emprego formal para "
               "gestores públicos. Os números sustentam as conclusões; não os enumere em sequência.\n"
               + REGRAS + EDITORIAL,
    "advisor": "Você é consultor de método em estatísticas do mercado de trabalho (Novo CAGED). Responde a uma "
               "dúvida de método de quem escreve um boletim municipal, em até 5 frases, sem números novos e sem "
               "especular causas. Se a resposta depender de conhecimento local, diga isso.",
    "revisor": "Você revisa um boletim de emprego formal escrito por outro modelo, com os fatos completos à mão. "
               "Aponte: número que não confere; linguagem causal ou especulação; afirmação sem base nos fatos "
               "(confira nos fatos antes de apontar: faixa histórica, gatilhos e sazonalidade estão lá); "
               "identificação de empresa; estrutura fora do pedido; estilo (considere os avisos de estilo "
               "recebidos). Marque como grave só o que não pode ser publicado. Não reescreva o texto.\n"
               + REGRAS + EDITORIAL,
}


def criar_agentes(criar_modelo) -> dict[str, Agent]:
    """Os três agentes. `criar_modelo(papel)` devolve o modelo de cada papel (OpenRouter em
    produção; FunctionModel nos testes)."""
    analista = Agent(criar_modelo("analista"), output_type=Analise, instructions=INSTRUCOES["analista"],
                     deps_type=Contexto, retries=1)
    redator = Agent(criar_modelo("redator"), output_type=Boletim, instructions=INSTRUCOES["redator"],
                    deps_type=Contexto, retries=1)
    revisor = Agent(criar_modelo("revisor"), output_type=Parecer, instructions=INSTRUCOES["revisor"], retries=1)

    @analista.output_validator
    def ids_existem(ctx: RunContext[Contexto], saida: Analise) -> Analise:
        faltando = sorted({i for d in saida.destaques for i in d.ids} - set(ctx.deps.numeros))
        if faltando and ctx.retry < ctx.max_retries:
            raise ModelRetry(f"Estes ids não existem na tabela `numeros`: {faltando}. Use só ids existentes.")
        return saida

    @redator.output_validator
    def numeros_conferem(ctx: RunContext[Contexto], saida: Boletim) -> Boletim:
        problemas = [p for p in verificar_texto(saida.texto(), ctx.deps.numeros, ctx.deps.rotulos)
                     if p["tipo"] == "numero_fora_dos_fatos"]
        ctx.deps.rejeicoes.append([p["numero"] for p in problemas])
        if problemas and ctx.retry < ctx.max_retries:
            lista = "; ".join(f"{p['numero']} em \"…{p['trecho']}…\"" for p in problemas[:15])
            raise ModelRetry("Estes números não estão na tabela `numeros` dos fatos (não calcule nem derive "
                             f"números): {lista}. Reescreva usando só valores da tabela.")
        return saida  # última tentativa: segue com o relatório para a revisão humana

    agentes = {"analista": analista, "redator": redator, "revisor": revisor}
    try:
        agentes["advisor"] = Agent(criar_modelo("advisor"), output_type=Orientacao, instructions=INSTRUCOES["advisor"],
                                   retries=1)
    except KeyError:
        pass  # execução sem advisor configurado
    return agentes


# --- tabelas (código, não LLM) -------------------------------------------------------------------

def _int(v) -> str:
    return "n/d" if v is None else f"{int(v):+,}".replace(",", ".") if v else "0"


def _qtd(v) -> str:
    return "n/d" if v is None else f"{int(v):,}".replace(",", ".")


def _pct(v) -> str:
    return "n/d" if v is None else f"{v:.2f}%".replace(".", ",")


def _v(item: dict | None, chave: str):
    x = (item or {}).get(chave)
    return x["valor"] if isinstance(x, dict) and "valor" in x else None


def tabelas(fatos: dict) -> str:
    """Tabelas de detalhe do boletim, geradas a partir dos fatos (revisão editorial, itens 10 e 19)."""
    md = ["## Tabelas", "", "### Grupamentos", "",
          "| grupamento | saldo | admissões | desligamentos | estoque | variação no mês |",
          "|---|---:|---:|---:|---:|---:|"]
    for nome, it in fatos["setorial"]["grupamentos"].items():
        md.append(f"| {nome} | {_int(_v(it, 'saldo'))} | {_qtd(_v(it, 'admissoes'))} | "
                  f"{_qtd(_v(it, 'desligamentos'))} | {_qtd(_v(it, 'estoque'))} | {_pct(_v(it, 'taxa_mes'))} |")
    c = fatos["comparacao"]
    blocos = [b for b in [c.get("territorio"), *c.get("regioes", []), c.get("uf")] if b]
    if blocos:
        md += ["", "### Comparação regional", "", "| território | saldo | estoque | variação no mês | variação em 12 meses |",
               "|---|---:|---:|---:|---:|"]
        for b in blocos:
            md.append(f"| {b['nome']} | {_int(_v(b, 'saldo'))} | {_qtd(_v(b, 'estoque'))} | "
                      f"{_pct(_v(b, 'taxa_mes'))} | {_pct(_v(b, 'taxa_12_meses'))} |")
    pix = (fatos.get("indicadores_externos") or {}).get("pix")
    if pix:
        md += ["", f"### Pix por município (Banco Central): empresas recebedoras e valor recebido, {pix['competencia']}", "",
               f"| território | empresas | variação desde {pix['comparado_com']} | R$ milhões | variação nominal |",
               "|---|---:|---:|---:|---:|"]
        for x in pix["recortes"]:
            md.append(f"| {x['nome']} | {_qtd(_v(x, 'empresas_recebedoras'))} | {_pct(_v(x, 'variacao_empresas_12m'))} | "
                      f"{str(_v(x, 'valor_recebido_milhoes')).replace('.', ',')} | {_pct(_v(x, 'variacao_valor_12m'))} |")
    for dim, titulo in (("sexo", "Admissões por sexo"), ("faixa_etaria", "Admissões por faixa etária")):
        cats = fatos["perfil"].get(dim) or {}
        if not cats:
            continue
        md += ["", f"### {titulo}", "", f"| categoria | admissões | participação | {fatos['rotulos']['ano_anterior']} | saldo |",
               "|---|---:|---:|---:|---:|"]
        for cat, it in cats.items():
            md.append(f"| {cat} | {_qtd(_v(it, 'admissoes'))} | {_pct(_v(it, 'participacao_admissoes'))} | "
                      f"{_pct(_v(it, 'participacao_admissoes_ano_anterior'))} | {_int(_v(it, 'saldo'))} |")
    return "\n".join(md) + "\n"


def leituras(evidencias: dict | None) -> str:
    """Leituras relacionadas (alternativa 3): as notícias relevantes, com link, sem afirmação.
    Geradas por código a partir da triagem."""
    if not evidencias:
        return ""
    itens = [t for t in evidencias.get("triadas", []) if t.get("relevante")]
    if not itens:
        return ""
    md = ["## Leituras relacionadas", ""]
    for t in sorted(itens, key=lambda t: t["publicado_em"], reverse=True):
        md.append(f"- [{t['titulo']}]({t['link']}), {t.get('veiculo') or t['fonte']}, {t['publicado_em'][:10]}")
    return "\n".join(md) + "\n"


def markdown(boletim: Boletim, fatos: dict, evidencias: dict | None = None) -> str:
    md = [f"# {boletim.titulo}", "", boletim.sintese, ""]
    for titulo, paragrafos in boletim.secoes():
        md += [f"## {titulo}", "", *[p + "\n" for p in paragrafos]]
    if boletim.pontos_de_atencao:
        md += ["## Pontos de atenção", ""] + [f"- {p}" for p in boletim.pontos_de_atencao] + [""]
    md += [tabelas(fatos), leituras(evidencias), "## Nota metodológica", "", boletim.nota_metodologica, ""]
    return "\n".join(md)


# --- orquestração --------------------------------------------------------------------------------

def modelos_do_ambiente(cfg: ia.ConfigIA) -> dict[str, str]:
    """IA_MODELO_<PAPEL>; sem eles, entre os permitidos que geram TEXTO: redator = 1º, analista e
    revisor = último (outra família, se houver duas). Advisor: IA_MODELO_ADVISOR, ou o 1º modelo de
    texto se não for o redator. Juiz: o 1º modelo de decisão permitido (Jev). Modelos de decisão
    nunca redigem."""
    texto = [m for m in cfg.modelos_permitidos if not e_modelo_de_decisao(m)]
    if not texto:
        raise RuntimeError("IA_MODELOS_PERMITIDOS sem nenhum modelo de texto: nenhum modelo pode redigir.")
    modelos = {
        "analista": os.environ.get("IA_MODELO_ANALISTA") or texto[-1],
        "redator": os.environ.get("IA_MODELO_REDATOR") or texto[0],
        "revisor": os.environ.get("IA_MODELO_REVISOR") or texto[-1],
    }
    advisor = os.environ.get("IA_MODELO_ADVISOR") or (texto[0] if texto[0] != modelos["redator"] else None)
    if advisor:
        modelos["advisor"] = advisor
    juiz = next((m for m in cfg.modelos_permitidos if e_modelo_de_decisao(m)), None)
    if juiz:
        modelos["juiz"] = juiz
    return modelos


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def _fatos_para_prompt(f: dict) -> str:
    return _json({k: v for k, v in f.items() if k != "hash"})


LIMIAR_AFIRMACAO = 0.5   # abaixo disso, a afirmação vai destacada para a revisão humana
LIMIAR_TRIAGEM = 0.6     # confiança mínima do Jev para descartar uma dúvida como "nenhuma"
MAX_ADVISOR = 2
CONHECIMENTO_NO_PROMPT = 20


class AguardandoResposta(RuntimeError):
    """Há ticket de fato local sem resposta: nada foi gerado (nem gasto) nesta execução."""


# --- tickets e conhecimento local (3b-2) ------------------------------------------------------

def arquivo_ticket(cfg: ia.ConfigIA, territorio: str, competencia: str, chave: str) -> Path:
    return cfg.pasta / "tickets" / f"{territorio}_{competencia}_{chave}.json"


def arquivo_conhecimento(cfg: ia.ConfigIA, territorio: str) -> Path:
    return cfg.pasta / "conhecimento" / f"{territorio}.jsonl"


def conhecimento_local(cfg: ia.ConfigIA, territorio: str) -> list[dict]:
    """As últimas respostas humanas a tickets do território (datadas): contexto, não fonte de número."""
    arq = arquivo_conhecimento(cfg, territorio)
    if not arq.exists():
        return []
    linhas = [json.loads(l) for l in arq.read_text(encoding="utf-8").splitlines() if l.strip()]
    return linhas[-CONHECIMENTO_NO_PROMPT:]


def responder_ticket(cfg: ia.ConfigIA, territorio: str, competencia: str, numero: int, resposta: str,
                     por: str) -> dict:
    """Registra a resposta humana à pergunta `numero` (1, 2...) do ticket aberto da competência e
    a acrescenta à base de conhecimento local do território."""
    abertos = sorted((cfg.pasta / "tickets").glob(f"{territorio}_{competencia}_*.json"))
    if not abertos:
        raise ValueError(f"Nenhum ticket para {territorio} em {competencia}.")
    arq = abertos[-1]
    t = json.loads(arq.read_text(encoding="utf-8"))
    pergunta = t["perguntas"][numero - 1]
    pergunta.update(resposta=resposta.strip(), respondido_por=por.strip(),
                    respondido_em=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    arq.write_text(_json(t) + "\n", encoding="utf-8")
    base = arquivo_conhecimento(cfg, territorio)
    base.parent.mkdir(parents=True, exist_ok=True)
    with base.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"competencia": competencia, "pergunta": pergunta["pergunta"], "resposta": pergunta["resposta"],
                            "respondido_por": pergunta["respondido_por"], "respondido_em": pergunta["respondido_em"]},
                           ensure_ascii=False) + "\n")
    return pergunta


def _numeros_de(fatos: dict, ids) -> dict:
    return {i: fatos["numeros"][i] for i in ids if i in fatos["numeros"]}


def triar_duvida(ex: ia.Execucao, duvida: Duvida, fatos: dict) -> dict:
    """O Jev classifica a dúvida (não se confia no rótulo do próprio LLM)."""
    estado = {"duvida": duvida.pergunta, "por_que": duvida.por_que, "fatos_relacionados": _numeros_de(fatos, duvida.ids),
              "municipio": fatos["territorio"]["nome"], "competencia": fatos["rotulos"]["competencia"]}
    r = ex.decidir(estado, {"tipo": {
        "type": "choice", "instructions": "Que tipo de resposta essa dúvida exige?",
        "criteria": {"fato_local": "Conhecimento sobre acontecimentos ou empresas do município, que os dados não trazem.",
                     "metodo": "Saber como ler ou comparar os dados (estatística, conceito do CAGED).",
                     "nenhuma": "Os fatos relacionados já respondem, ou a dúvida não muda o texto."}}})
    tipo = r.get("tipo") or {}
    return {"pergunta": duvida.pergunta, "tipo_llm": duvida.tipo, "tipo_jev": tipo.get("choice"),
            "confianca_jev": tipo.get("confidence"), "probabilidades": tipo.get("probabilities")}


def julgar_afirmacoes(ex: ia.Execucao, boletim: Boletim, fatos: dict) -> list[dict]:
    """O Jev julga se os fatos citados sustentam cada afirmação interpretativa do texto."""
    if not boletim.afirmacoes:
        return []
    setorial = fatos.get("setorial", {})
    contexto = {"gatilhos": fatos.get("gatilhos"), "destaques": setorial.get("destaques"),
                "posicoes_na_faixa_historica": {
                    "total": fatos.get("panorama", {}).get("sazonalidade", {}).get("posicao"),
                    **{g: it.get("sazonalidade", {}).get("posicao") for g, it in setorial.get("grupamentos", {}).items()}}}
    julgadas = []
    for a in boletim.afirmacoes:
        citados = _numeros_de(fatos, a.ids)
        r = ex.decidir({"afirmacao": a.texto, "fatos_citados": citados, "contexto": contexto}, {"sustentada": {
            "type": "noul", "instructions": "Os fatos citados e o contexto sustentam a afirmação, sem exagero e sem causa?",
            "criteria": {"true": "Os fatos sustentam exatamente o que a afirmação diz.",
                         "false": "Os fatos não sustentam, contradizem, ou a afirmação atribui causa ou exagera."}}})
        p = (r.get("sustentada") or {}).get("noul")
        julgadas.append({"texto": a.texto, "ids": a.ids, "ids_inexistentes": sorted(set(a.ids) - set(citados)),
                         "probabilidade": p, "sustentada": p is not None and p >= LIMIAR_AFIRMACAO and len(citados) == len(a.ids)})
    return julgadas


# --- orquestração ----------------------------------------------------------------------------------

def gerar(fatos: dict, cfg: ia.ConfigIA, modelos: dict[str, str], *, criar_modelo=None,
          precos: ia.Precos | None = None, registro: ia.RegistroCustos | None = None,
          refazer: bool = False, evidencias: dict | None = None, sem_tickets: bool = False,
          post_decisoes=None) -> dict:
    """Gera (ou reaproveita) o boletim com IA de um JSON de fatos. Devolve o resultado gravado, ou
    {"situacao": "aguardando_resposta", ...} quando abriu ticket de fato local."""
    texto_errado = {p: m for p, m in modelos.items() if p != "juiz" and e_modelo_de_decisao(m)}
    if texto_errado:
        raise ValueError(f"Modelos de decisão não redigem texto: {texto_errado}. Use-os como juiz.")
    territorio, competencia = fatos["territorio"]["codigo"], fatos["competencia"]
    chave = fatos["hash"][:16]
    lista_evid = (evidencias or {}).get("evidencias", [])
    if evidencias:
        chave += "_" + hashlib.sha256(json.dumps(evidencias, sort_keys=True, default=str).encode()).hexdigest()[:8]
    pasta = cfg.pasta / "boletins" / f"{territorio}_{competencia}" / chave
    arquivo = pasta / "resultado.json"
    if arquivo.exists() and not refazer:
        resultado = json.loads(arquivo.read_text(encoding="utf-8"))
        resultado["reaproveitado"] = True
        resultado["pasta"] = str(pasta)
        return resultado

    # Ticket aberto para estes fatos: sem resposta, nada roda (nem gasta); com resposta, retoma
    # da análise salva, sem pagar o analista de novo.
    ticket = arquivo_ticket(cfg, territorio, competencia, chave)
    salvo = json.loads(ticket.read_text(encoding="utf-8")) if ticket.exists() else None
    if salvo and not sem_tickets:
        pendentes = [q["pergunta"] for q in salvo["perguntas"] if not q.get("resposta")]
        if pendentes:
            raise AguardandoResposta(f"Ticket {ticket.name} com {len(pendentes)} pergunta(s) sem resposta: {pendentes}")

    criar_modelo = criar_modelo or (lambda papel: ia.modelo_openrouter(cfg, modelos[papel], papel))
    agentes = criar_agentes(criar_modelo)
    contexto = Contexto(fatos, lista_evid)
    decisoes: list[dict] = []
    with ia.Execucao(cfg, modelos, precos=precos, registro=registro,
                     territorio=territorio, competencia=competencia) as ex:
        if post_decisoes:
            ex.post_decisoes = post_decisoes
        base = _fatos_para_prompt(fatos)
        conhecimento = conhecimento_local(cfg, territorio)
        bloco_conhecimento = ("Conhecimento local registrado por pessoas (contexto datado; não é fonte de números):\n"
                              + _json(conhecimento)) if conhecimento else ""

        if salvo:
            analise = Analise(**salvo["analise"])
            orientacoes = salvo.get("orientacoes", [])
            respostas = [q for q in salvo["perguntas"] if q.get("resposta")]
            decisoes = salvo.get("decisoes", []) + [{"tipo": "retomada_do_ticket", "arquivo": ticket.name}]
        else:
            analise = ex.rodar(agentes["analista"], "analista",
                               f"Fatos do mês (JSON):\n{base}\n\n{bloco_conhecimento}", deps=contexto)
            orientacoes, respostas, locais = [], [], []
            for d in analise.duvidas:
                if "juiz" in modelos:
                    t = triar_duvida(ex, d, fatos)
                    tipo = t["tipo_jev"] or d.tipo
                    if tipo == "nenhuma" and (t["confianca_jev"] or 0) < LIMIAR_TRIAGEM:
                        tipo = d.tipo  # Jev pouco confiante em descartar: segue o rótulo do LLM
                else:
                    t, tipo = {"pergunta": d.pergunta, "tipo_llm": d.tipo}, d.tipo
                decisoes.append({"tipo": "triagem_de_duvida", **t, "destino": tipo})
                if tipo == "metodo" and "advisor" in agentes and "advisor" in modelos \
                        and sum(1 for o in orientacoes) < MAX_ADVISOR:
                    o: Orientacao = ex.rodar(agentes["advisor"], "advisor",
                                             f"Dúvida: {d.pergunta}\nPor quê: {d.por_que}\n"
                                             f"Fatos relacionados: {_json(_numeros_de(fatos, d.ids))}")
                    orientacoes.append({"pergunta": d.pergunta, **o.model_dump()})
                elif tipo == "fato_local":
                    locais.append({"pergunta": d.pergunta, "por_que": d.por_que, "ids": d.ids})
            if locais and not sem_tickets:
                ticket.parent.mkdir(parents=True, exist_ok=True)
                ticket.write_text(_json({"territorio": territorio, "competencia": competencia, "chave": chave,
                                         "aberto_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                         "analise": analise.model_dump(), "orientacoes": orientacoes,
                                         "decisoes": decisoes, "perguntas": locais}) + "\n", encoding="utf-8")
                return {"situacao": "aguardando_resposta", "ticket": str(ticket), "perguntas": [q["pergunta"] for q in locais],
                        "execucao": ex.id, "decisoes": decisoes}
            if locais:  # --sem-tickets: o redator é avisado para não afirmar nada sobre isso
                respostas = [{"pergunta": q["pergunta"], "resposta": "SEM RESPOSTA: não afirme nada sobre isso."}
                             for q in locais]

        if lista_evid:
            bloco_evid = ("Evidências externas (notícias; siga as regras de janela):\n"
                          + _json([{k: e.get(k) for k in ("fato", "numeros", "fonte", "data", "janela", "apoia_hipotese", "setor", "territorio")}
                                   for e in lista_evid]))
        else:
            bloco_evid = "Evidências externas: nenhuma. Não cite fontes externas nem acontecimentos."
        extras = ""
        if orientacoes:
            extras += "\n\nOrientações de método do advisor (siga-as; não cite o advisor):\n" + _json(orientacoes)
        if respostas:
            extras += ("\n\nRespostas de pessoas a dúvidas de fato local (contexto; atribua como informação "
                       "local, sem números novos):\n" + _json(respostas))
        if bloco_conhecimento:
            extras += "\n\n" + bloco_conhecimento
        pedido = (f"Fatos do mês (JSON):\n{base}\n\nAnálise do analista (JSON):\n{analise.model_dump_json(indent=2)}\n\n"
                  + bloco_evid + extras)
        boletim: Boletim = ex.rodar(agentes["redator"], "redator", pedido, deps=contexto)
        estilo = avisos_de_estilo(boletim.texto())
        parecer: Parecer = ex.rodar(agentes["revisor"], "revisor",
                                    f"Fatos completos (JSON):\n{base}\n\n{bloco_evid}\n\nBoletim (JSON):\n{boletim.model_dump_json(indent=2)}\n\n"
                                    f"Avisos de estilo do verificador:\n{_json(estilo)}")
        versoes = 1
        # Segunda versão: problema grave do revisor OU estilo com vários avisos (a convenção de
        # sinal e as expressões proibidas o redator costuma ignorar na primeira passada).
        if any(p.gravidade == "grave" for p in parecer.problemas) or len(estilo) >= AVISOS_PARA_NOVA_VERSAO:
            boletim = ex.rodar(agentes["redator"], "redator",
                               f"{pedido}\n\nSua versão anterior (JSON):\n{boletim.model_dump_json(indent=2)}\n\n"
                               f"Problemas apontados pelo revisor (corrija os graves e os de estilo):\n{parecer.model_dump_json(indent=2)}\n\n"
                               f"Avisos de estilo (corrija todos):\n{_json(estilo)}",
                               deps=contexto)
            versoes = 2
        afirmacoes = julgar_afirmacoes(ex, boletim, fatos) if "juiz" in modelos else []
        decisoes += [{"tipo": "julgamento_de_afirmacao", **a} for a in afirmacoes]
        execucao_id = ex.id

    boletim = boletim.com_milhares()
    problemas = verificar_texto(boletim.texto(), contexto.numeros, contexto.rotulos)
    reprovado = any(p["tipo"] == "numero_fora_dos_fatos" for p in problemas)
    resultado = {
        "territorio": territorio,
        "competencia": competencia,
        "hash_fatos": fatos["hash"],
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "execucao": execucao_id,
        "modelos": modelos,
        "situacao": "reprovado_no_verificador" if reprovado else "aguardando_aprovacao",
        "versoes_do_redator": versoes,
        "verificador": problemas,
        "rejeicoes_do_verificador": contexto.rejeicoes,  # números reprovados em cada tentativa
        "avisos_de_estilo": avisos_de_estilo(boletim.texto()),
        "afirmacoes_nao_sustentadas": [a for a in afirmacoes if not a["sustentada"]],
        "orientacoes_do_advisor": orientacoes,
        "respostas_humanas": respostas,
        "decisoes": decisoes,  # registro de decisões (3b-2): triagens, retomadas, julgamentos
        "parecer_revisor": parecer.model_dump(),
        "analise": analise.model_dump(),
        "evidencias_usadas": lista_evid,
        "leituras": [{"titulo": t["titulo"], "link": t["link"], "fonte": t.get("veiculo") or t["fonte"],
                      "data": t["publicado_em"][:10]}
                     for t in (evidencias or {}).get("triadas", []) if t.get("relevante")],
        "boletim": boletim.model_dump(),
    }
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "fatos.json").write_text(_json(fatos) + "\n", encoding="utf-8")
    (pasta / "boletim.md").write_text(markdown(boletim, fatos, evidencias), encoding="utf-8")
    arquivo.write_text(_json(resultado) + "\n", encoding="utf-8")
    resultado["pasta"] = str(pasta)
    return resultado


def main():
    ap = argparse.ArgumentParser(description="Gera o boletim com IA (F19); fica aguardando aprovação.")
    ap.add_argument("territorio")
    ap.add_argument("competencia")
    ap.add_argument("--warehouse", default="/data/warehouse/caged.duckdb")
    ap.add_argument("--refazer", action="store_true", help="gera de novo mesmo com resultado para estes fatos")
    ap.add_argument("--com-evidencias", action="store_true", help="seleciona, tria e pesquisa notícias (parte 4)")
    ap.add_argument("--gerado-em", default=datetime.now(timezone.utc).date().isoformat())
    ap.add_argument("--sem-indicadores", action="store_true", help="não busca Pix e Selic no Banco Central")
    ap.add_argument("--sem-tickets", action="store_true", help="não abre ticket: dúvidas de fato local ficam sem afirmação")
    ap.add_argument("--responder", type=int, metavar="N", help="responde a pergunta N do ticket aberto e sai")
    ap.add_argument("--resposta", default="")
    ap.add_argument("--por", default="", help="quem respondeu (com --responder)")
    a = ap.parse_args()
    cfg = ia.ConfigIA.do_ambiente()
    if a.responder:
        if not a.resposta.strip() or not a.por.strip():
            raise SystemExit("--responder exige --resposta e --por.")
        q = responder_ticket(cfg, a.territorio, a.competencia, a.responder, a.resposta, a.por)
        print(f"Resposta registrada para: {q['pergunta']}. Rode o comando de geração de novo para retomar.")
        return
    f = fatos_mod.gerar_fatos(Path(a.warehouse), a.territorio, a.competencia)
    if not a.sem_indicadores:
        import indicadores
        f = indicadores.anexar(f, Path(a.warehouse))
    try:
        evid = None
        if a.com_evidencias:
            import evidencias as evidencias_mod
            from datetime import date
            evid = evidencias_mod.gerar_evidencias(f, Path(a.warehouse), cfg, date.fromisoformat(a.gerado_em))
        r = gerar(f, cfg, modelos_do_ambiente(cfg), refazer=a.refazer, evidencias=evid, sem_tickets=a.sem_tickets)
    except AguardandoResposta as e:
        raise SystemExit(f"Aguardando resposta humana: {e}\nResponda com --responder N --resposta \"...\" --por \"Nome\".")
    except ia.OrcamentoExcedido as e:
        raise SystemExit(f"Recusado pelo orçamento: {e}")
    except Exception as e:
        # 401/402/403 da OpenRouter: chave inválida, sem crédito ou limite da chave atingido
        # (o limite é vitalício e reajustado à mão todo mês).
        if any(c in str(e) for c in ("401", "402", "403")):
            raise SystemExit(f"A OpenRouter recusou a chamada ({e}). Confira a chave e o limite de crédito dela.")
        raise
    if r["situacao"] == "aguardando_resposta":
        print(json.dumps({"situacao": r["situacao"], "ticket": r["ticket"], "perguntas": r["perguntas"]},
                         ensure_ascii=False, indent=2))
        print("Responda com: python flows/boletim_ia.py T C --responder N --resposta \"...\" --por \"Nome\"")
        return
    print(json.dumps({k: r[k] for k in ("situacao", "execucao", "modelos", "versoes_do_redator")}
                     | {"reaproveitado": r.get("reaproveitado", False), "problemas_verificador": len(r["verificador"]),
                        "rejeicoes": r.get("rejeicoes_do_verificador"), "avisos_de_estilo": len(r.get("avisos_de_estilo", [])),
                        "problemas_revisor": len(r["parecer_revisor"]["problemas"]), "pasta": r.get("pasta")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
