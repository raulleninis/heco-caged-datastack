"""
Boletim com IA (F19 parte 3, revista na 3b-1): analista → redator → revisor, sobre os fatos da
parte 1, dentro das proteções da parte 2. Resultado fica AGUARDANDO APROVAÇÃO humana; nada é
enviado aqui.

Fluxo fixo, sem agente decidindo chamar outro (docs/fatias/F19-boletim-com-ia.md):

1. fatos (flows/fatos.py), com hash. Mesmo hash e resultado já gerado: reaproveita, sem LLM
   (só gera de novo com --refazer).
2. analista: escolhe até 5 destaques, citando ids de `numeros`.
3. redator: escreve o texto na estrutura do roteiro (síntese, evolução do emprego, setores,
   comparação regional e perfil, o que acompanhar), só com os números de `numeros_do_texto`
   (o resto fica nas tabelas; revisão editorial de 30/09/2026). O verificador de
   números é o seu output_validator: número fora dos fatos gera UMA nova tentativa; na última,
   o texto é aceito e segue com o relatório para a revisão humana (em vez de abortar e perder o
   que foi pago). As rejeições de cada tentativa ficam registradas.
4. revisor (outra família de modelo, com os fatos COMPLETOS e os avisos de estilo): parecer
   sobre causalidade, fontes, rótulos, identificação e estilo. Problema grave gera uma segunda
   versão do redator, verificada de novo.
5. grava fatos.json, resultado.json e boletim.md. Cards, TABELAS e a nota metodológica são
   gerados por código a partir dos fatos (dois níveis: o texto interpreta, a tabela detalha); o
   LLM nunca monta tabela e não repete o que está nos cards (`numeros_nos_cards`).

Revisão editorial de 01/10/2026: diretrizes do usuário no EDITORIAL (hierarquia, panorama sem
repetir os cards, faixa histórica como complemento, profundidade proporcional nos setores, saldo
por sexo antes da composição, regra de corte) e o Pix de volta ao texto como "sinais da atividade
econômica", com meses posteriores ao CAGED como sinal a acompanhar, nunca previsão.

Pior caso de requisições: analista 2 + redator 2 + revisor 1 + redator 2 = 7, dentro do
request_limit de 8 da Execucao. Sem hipóteses: o boletim descreve, não explica.

Escopo fechado nos fatos (01/10/2026): o boletim só afirma o que os fatos mostram, sem
informação externa. Dúvida do analista que exigiria informação de fora (acontecimentos, obras,
deslocamentos) não para a geração nem pergunta a ninguém: o redator é instruído a não afirmar
nada sobre ela. Dúvida de método vai ao advisor, que orienta a leitura sem trazer dado novo. Os
tickets e a base de conhecimento local (3b-2) saíram.

Uso:
    python flows/boletim_ia.py 280480 202607 [--refazer] [--warehouse ...]
"""

import argparse
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext, UnexpectedModelBehavior

import fatos as fatos_mod
import ia
from verificador import avisos_de_estilo, formatar_milhares, numeros_de_tabela, rotulos_dos_fatos, verificar_texto

# Avisos de estilo que, sozinhos, justificam uma segunda versão do redator (~US$ 0,02).
AVISOS_PARA_NOVA_VERSAO = 3

e_modelo_de_decisao = ia.e_modelo_de_decisao  # modelos de decisão (Jev) não redigem


# --- saídas tipadas ---------------------------------------------------------------------------


class Destaque(BaseModel):
    tema: str
    ids: list[str] = Field(min_length=1, description="ids da tabela `numeros` que sustentam o destaque")
    por_que: str = Field(description="qual regra ou gatilho o torna destaque")


class Duvida(BaseModel):
    """3b-2: o que o analista não consegue decidir só com os fatos."""
    pergunta: str
    tipo: Literal["fora_dos_fatos", "metodo"] = Field(
        description="fora_dos_fatos: exigiria informação que os fatos não trazem (acontecimentos, obras, "
                    "deslocamentos); o boletim não afirma nada sobre isso. metodo: como ler os dados")
    ids: list[str] = Field(default_factory=list, description="ids de `numeros` relacionados")
    por_que: str


class Analise(BaseModel):
    destaques: list[Destaque] = Field(max_length=5)
    desagregacoes: list[str] = Field(default_factory=list, description="códigos de `desagregacao` a usar no texto")
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
    """A nota metodológica não é do LLM: sai por código (`nota_metodologica`)."""
    titulo: str
    sintese: str = Field(description="UMA frase: o resultado do mês e onde se concentrou (sem o estoque)")
    panorama: list[str] = Field(description="interpretação, sem repetir os cards: melhorou ou piorou frente ao mesmo "
                                            "mês do ano anterior e por quê (admissões, desligamentos ou ambos); "
                                            "acumulado no ano e em 12 meses; faixa histórica só se fora dela")
    setores: list[str] = Field(description="os 2 ou 3 movimentos que mais explicam o resultado, com profundidade "
                                           "proporcional: o principal com a atividade responsável e as demais "
                                           "atividades; os grupamentos restantes numa frase, só com o saldo conjunto")
    contexto_regional: list[str] = Field(max_length=1, description="UMA frase, sem números: o município frente à "
                                                                   "região e à UF (a tabela traz as taxas)")
    perfil_e_remuneracao: list[str] = Field(description="saldo por sexo primeiro; até 3 faixas etárias pelas maiores "
                                                        "perdas ou ganhos; remuneração sem repetir o card")
    sinais_da_atividade: list[str] = Field(default_factory=list, max_length=1,
                                           description="UM parágrafo sobre o Pix como indicador complementar, "
                                                       "seguindo o modelo das regras do Pix; obrigatório quando "
                                                       "os fatos trazem Pix")
    pontos_de_atencao: list[str] = Field(max_length=3, description="o que verificar nas próximas edições (ex.: 'se a "
                                                                   "retração de X persiste em agosto'); não repita o texto")
    afirmacoes: list[Afirmacao] = Field(default_factory=list, max_length=10,
                                        description="as afirmações INTERPRETATIVAS do texto (posição na faixa histórica, "
                                                    "concentração, comparação entre territórios, perfil), cada uma com os "
                                                    "ids que a sustentam. Não liste 'subiu/caiu' frente ao ano anterior: "
                                                    "isso o verificador de números já confere")

    def secoes(self) -> list[tuple[str, list[str]]]:
        return [("Evolução do emprego", self.panorama), ("Setores", self.setores),
                ("Comparação regional e perfil", self.contexto_regional + self.perfil_e_remuneracao),
                ("Sinais da atividade econômica: Pix", self.sinais_da_atividade)]

    def texto(self) -> str:
        partes = [self.titulo, self.sintese]
        for _, paragrafos in self.secoes():
            partes += paragrafos
        return "\n".join(partes + self.pontos_de_atencao)

    def com_milhares(self) -> "Boletim":
        """Mesmo texto com separador de milhar (formatação por código, valor inalterado)."""
        f = formatar_milhares
        return self.model_copy(update={
            "titulo": f(self.titulo), "sintese": f(self.sintese), "panorama": [f(x) for x in self.panorama],
            "setores": [f(x) for x in self.setores], "contexto_regional": [f(x) for x in self.contexto_regional],
            "perfil_e_remuneracao": [f(x) for x in self.perfil_e_remuneracao],
            "sinais_da_atividade": [f(x) for x in self.sinais_da_atividade],
            "pontos_de_atencao": [f(x) for x in self.pontos_de_atencao]})


class Problema(BaseModel):
    # Texto livre: só informa. Um Literal aqui derrubou o parecer do GLM 5.3 Flash (29/09/2026).
    tipo: str = Field(description="numero, causalidade, fonte, rotulo, identificacao, estilo ou estrutura")
    gravidade: Literal["grave", "menor"]
    trecho: str
    sugestao: str


class Parecer(BaseModel):
    problemas: list[Problema] = Field(default_factory=list)
    resumo: str


@dataclass
class Contexto:
    """deps dos agentes: a tabela de números, os rótulos aceitos e o registro das rejeições."""
    fatos: dict
    rejeicoes: list[list[str]] = field(default_factory=list)

    @property
    def numeros(self) -> dict:
        return self.fatos["numeros"]

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
- Não atribua causa. Descreva o que os dados mostram e separe o fato observado de qualquer
  leitura sua. Não há hipóteses nesta versão: não especule sobre motivos.
- Salário: a mediana é a referência. A comparação com o ano anterior é NOMINAL (sem correção
  pela inflação): diga isso. A média não precisa aparecer.
- Categorias com `base_pequena` ou `sem_identificacao` não são interpretadas nem citadas.
- Selic (`indicadores_externos`), quando houver: só como contexto para os setores sensíveis a
  crédito em destaque; nunca como causa.
- Não cite notícias, acontecimentos nem fontes externas.
"""

EDITORIAL = """\
Leitor: gestor público, que precisa responder em poucos minutos: (1) o emprego formal aumentou
ou diminuiu? (2) qual setor ou atividade explica principalmente o resultado? (3) está melhor ou
pior que no mesmo mês do ano anterior? (4) o município acompanha ou destoa da região e do
estado? (5) algum grupo de trabalhadores teve comportamento especialmente relevante? (6) o que
acompanhar no próximo mês? O que não ajuda a responder a essas perguntas fica fora do texto.

Princípio central: o texto INTERPRETA; cards, tabelas e gráficos, gerados por código, APRESENTAM
os números. Antes de pôr um dado no texto, pergunte se ele ajuda a entender o que aconteceu, onde
aconteceu ou por que merece atenção. Se não ajuda, deixe-o fora. Não leia tabela em voz alta.
- No texto, use só números de `numeros_do_texto`. Os de `numeros_nos_cards` já aparecem em
  destaque no boletim: não os repita, salvo quando indispensáveis para uma comparação. Cada
  número entra uma vez só no texto.
- Hierarquia, nesta ordem: resultado geral; setores ou atividades que mais o explicam; mudança
  frente ao mesmo mês do ano anterior; acumulado no ano e em 12 meses; diferença frente à região
  e à UF; mudanças no perfil; remuneração; indicadores complementares. O espaço de cada assunto é
  proporcional à sua contribuição para o resultado: movimento pequeno não ganha parágrafo.

Seções:
- Síntese: UMA frase com o resultado do mês e onde se concentrou. Sem o estoque.
- Panorama (`panorama`): NÃO repita admissões, desligamentos nem estoque (estão nos cards).
  Comece pela interpretação: o resultado melhorou ou piorou frente ao mesmo mês do ano anterior
  (pelo nome, do campo `rotulos`, com o saldo daquele mês) e se a mudança veio de menos
  admissões, de mais desligamentos ou de ambos (`decomposicao`, sem repetir as diferenças, que
  estão nos cards). Depois, o acumulado no ano e em 12 meses numa frase ("No ano, perda de 188
  vínculos; em 12 meses, saldo positivo de 190"), sem explicar a diferença entre os períodos. A
  faixa histórica é referência complementar, mostrada num gráfico: cite-a só quando o mês ficou
  ACIMA ou ABAIXO dela. "Dentro da faixa" nunca é a interpretação principal: o intervalo costuma
  ser amplo e sugere uma normalidade que o indicador não garante.
- Setores: aprofunde só os dois ou três movimentos que mais explicam o resultado municipal. O
  principal com a atividade responsável (`desagregacao`, `nome` na seção) e, quando ela explica
  parcela alta do setor, o saldo das demais atividades em conjunto; os outros destaques numa
  frase cada; os grupamentos restantes numa frase só, com o saldo conjunto de
  `fora_dos_destaques`. No texto, só o saldo, a atividade principal e, se relevante, a
  comparação com o ano anterior ou a posição fora da faixa histórica; admissões, desligamentos,
  estoque e taxas ficam nas tabelas. Prefira "Serviços perdeu 181 vínculos" a "o grupamento
  apresentou saldo negativo de 181"; para o resto do setor, "as demais atividades somaram perda
  de 2 vínculos".
- Contexto regional: UMA frase, sem números, dizendo como o município se saiu frente à região e
  à UF no mês e em 12 meses. Compare TAXAS; nunca saldos absolutos de territórios de tamanhos
  diferentes (o município faz parte da região e da UF).
- Perfil e remuneração: só resultados com diferença relevante, concentração elevada ou mudança
  importante frente ao ano anterior (`relevante` = true). Priorize o SALDO por sexo, mais
  informativo que a composição ("Embora respondessem por apenas 27,14% das admissões, as
  mulheres perderam 171 vínculos, enquanto os homens ganharam 92"); a composição vem depois, só
  se acrescentar algo. Faixa etária: no máximo três categorias, pelas maiores perdas ou ganhos
  de saldo, numa frase curta ("As maiores perdas ocorreram entre 25 e 29 anos, 30 e 39 e 18 e 24;
  a faixa de 40 a 49 foi a única com ganho"); a mudança de participação só entra se for um sinal
  relevante a acompanhar. Remuneração: o card já mostra a mediana e a variação nominal; no texto,
  no máximo uma frase que acrescente algo (a mediana do ano anterior), dizendo que a comparação é
  nominal, sem correção pela inflação. Nunca média e mediana juntas.
- Sinais da atividade econômica (`sinais_da_atividade`): UM parágrafo, OBRIGATÓRIO sempre que os
  fatos trouxerem `indicadores_externos.pix`. Siga as regras e o modelo do Pix abaixo.
- Pontos de atenção: no máximo 3 itens sobre o que VERIFICAR nas próximas edições ("verificar se
  a retração de X persiste", "acompanhar se o crescimento de Y continua", "observar se a mudança
  de perfil se mantém"). Não repita o que já aconteceu; sem números; sem especular.
- Não escreva nota metodológica nem mencione a provisoriedade: a nota sai por código.

Pix (`indicadores_externos.pix`): indicador COMPLEMENTAR de atividade econômica, nunca medida de
emprego nem prova de crescimento ou retração da economia. O CAGED olha para trás; o Pix aproxima
o boletim do presente: além do retrato do emprego no mês, o gestor recebe um pequeno radar do que
veio depois. Deixe clara a diferença entre indicador complementar e previsão.
- Prioridade: o VALOR recebido, lido junto com o número de empresas (que, sozinho, é muito
  contaminado pela própria expansão do Pix). Compare SEMPRE o município com a Região Metropolitana
  e a UF (a comparação relativa informa mais que o crescimento isolado, porque parte da alta vem
  da adoção do Pix, da inflação e da troca de dinheiro e cartão por Pix) e olhe a trajetória
  (`pix.anteriores`, o mês da competência e `pix.posteriores`).
- Meses posteriores à competência do CAGED (`pix.posteriores`), quando houver: apresente-os
  explicitamente como dados POSTERIORES ao período do emprego, sinal do comportamento recente da
  atividade e informação para as próximas competências.
- Modelo de redação (adapte os números e o que os dados mostram; sem posteriores, omita a frase
  deles): "Como indicador complementar, os dados de Pix ajudam a acompanhar a evolução recente
  das transações realizadas por empresas cadastradas no município. Em [mês], [município]
  registrou crescimento de X% no valor movimentado em relação ao mesmo mês do ano anterior,
  frente a Y% na [região] e Z% em [UF]. Dados de [mês seguinte], já disponíveis, mostram [...].
  Embora o Pix não permita antecipar o resultado do emprego formal,
  seu comportamento oferece um sinal adicional a ser acompanhado nas próximas divulgações do
  CAGED."
- Use "sinal a acompanhar", "indício complementar", "comportamento recente da atividade",
  "informação adicional para as próximas competências". Nunca "indica que o emprego crescerá",
  "antecipa o resultado do CAGED", "comprova aquecimento da economia", "explica a geração (ou
  perda) de empregos", nem "proxy do aquecimento da economia".

Corte: antes de entregar, releia o texto só para reduzi-lo. Tire informações repetidas, números
que estão nos cards ou nas tabelas, explicações óbvias e enumerações longas; cada parágrafo com
uma mensagem principal. Mire em 15% a 25% menos que a primeira versão, sem perder conclusão
relevante.

Convenções: "perda de 83 vínculos", "perdeu 83 vínculos" ou "saldo negativo de 83", sem sinal de
menos; percentuais SEMPRE com 2 casas decimais (0,33%); "vínculos" para tudo (não alterne com
postos, vagas, empregos). Títulos só com a primeira letra maiúscula. Frases curtas e diretas
("teve", "foi", "caiu"). Sem travessão. Sem gerúndio decorativo ("destacando-se",
"evidenciando"). Sem "vale ressaltar", "no tocante", "cenário", "impulsionado".
"""

INSTRUCOES = {
    "analista": "Você é o analista de um boletim mensal de emprego formal (Novo CAGED). Recebe os fatos já "
                "calculados e escolhe o que merece destaque, seguindo os `gatilhos` e os `destaques` setoriais. "
                "Cada destaque cita ids da tabela `numeros`. O boletim só afirma o que os fatos mostram, sem "
                "informação externa: não levante dúvida para buscar acontecimentos, obras ou deslocamentos; "
                "se algo só se explicaria com isso, simplesmente não se afirma. Antes de perguntar, confira "
                "se os fatos já respondem (faixa histórica do mesmo mês, gatilhos). Dúvidas (`duvidas`): só as que "
                "mudariam o texto; NUNCA sobre empresas ou estabelecimentos, nem 'um ou poucos "
                "estabelecimentos' (vira identificação): formule no nível do setor ou do município.\n" + REGRAS,
    "redator": "Você redige, em português do Brasil, o texto de um boletim mensal de emprego formal para "
               "gestores públicos. Os números sustentam as conclusões; não os enumere em sequência.\n"
               + REGRAS + EDITORIAL,
    "advisor": "Você é consultor de método em estatísticas do mercado de trabalho (Novo CAGED). Responde a uma "
               "dúvida de método de quem escreve um boletim municipal, em até 5 frases, sem números novos e sem "
               "especular causas. Se a resposta exigir informação que os dados não trazem, diga que o boletim não deve "
               "afirmar nada sobre isso.",
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
        pedidos = []
        if problemas:
            lista = "; ".join(f"{p['numero']} em \"…{p['trecho']}…\"" for p in problemas[:15])
            pedidos.append("Estes números não estão na tabela `numeros` dos fatos (não calcule nem derive "
                           f"números): {lista}. Reescreva usando só valores da tabela.")
        if (ctx.deps.fatos.get("indicadores_externos") or {}).get("pix") and not saida.sinais_da_atividade:
            pedidos.append("Falta `sinais_da_atividade`: com Pix nos fatos, escreva o parágrafo seguindo o "
                           "modelo das regras do Pix.")
        if pedidos and ctx.retry < ctx.max_retries:
            raise ModelRetry(" ".join(pedidos))
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


def complementares(fatos: dict) -> str:
    """Indicadores complementares (Pix), fora do texto: a ponte com o CAGED não é direta
    (revisão editorial de 30/09/2026). Tabela e cuidado de leitura, por código."""
    pix = (fatos.get("indicadores_externos") or {}).get("pix")
    if not pix:
        return ""
    md = ["## Sinais da atividade econômica: Pix (tabelas)", "",
          f"### Valor recebido e empresas recebedoras (Banco Central), {pix['competencia']}", "",
          f"| território | R$ milhões | variação nominal desde {pix['comparado_com']} | empresas | variação |",
          "|---|---:|---:|---:|---:|"]
    for x in pix["recortes"]:
        md.append(f"| {x['nome']} | {str(_v(x, 'valor_recebido_milhoes')).replace('.', ',')} | "
                  f"{_pct(_v(x, 'variacao_valor_12m'))} | {_qtd(_v(x, 'empresas_recebedoras'))} | "
                  f"{_pct(_v(x, 'variacao_empresas_12m'))} |")
    trajetoria = trajetoria_pix(pix)
    if len(trajetoria) > 1:
        nomes = [x["nome"] for x in pix["recortes"]]
        md += ["", "### Trajetória: variação do valor recebido em 12 meses (* posterior ao CAGED)", "",
               "| mês | " + " | ".join(nomes) + " |", "|---|" + "---:|" * len(nomes)]
        for rotulo, valores in trajetoria:
            md.append(f"| {rotulo} | " + " | ".join(_pct(v) for v in valores) + " |")
    if pix.get("cuidados"):
        md += ["", pix["cuidados"]]
    return "\n".join(md) + "\n"


def trajetoria_pix(pix: dict) -> list[tuple[str, list]]:
    """(mês, variações do valor em 12 meses por recorte) dos meses anteriores, da competência e
    dos posteriores (marcados com *), na ordem dos recortes da competência."""
    nomes = [x["nome"] for x in pix.get("recortes", [])]

    def linha(rotulo, recortes):
        por_nome = {x["nome"]: _v(x, "variacao_valor_12m") for x in recortes}
        return rotulo, [por_nome.get(n) for n in nomes]

    return ([linha(m["competencia"], m["recortes"]) for m in pix.get("anteriores", [])]
            + [linha(pix["competencia"], pix.get("recortes", []))]
            + [linha(f"{m['competencia']}*", m["recortes"]) for m in pix.get("posteriores", [])])


def nota_metodologica(fatos: dict) -> str:
    """A nota, por código: curta e igual em todas as edições."""
    frases = ["Os dados do Novo CAGED são provisórios."]
    anos = (fatos.get("panorama", {}).get("sazonalidade") or {}).get("anos")
    if anos:
        mes = fatos["rotulos"]["competencia"].split()[0]
        frases.append(f"A faixa histórica considera os meses de {mes} de {anos[0]} a {anos[-1]}.")
    frases.append("Categorias com poucas observações não são interpretadas.")
    base = ((fatos.get("salario") or {}).get("base") or {}).get("valor")
    if base:
        frases.append(f"A remuneração considera {_qtd(base)} admissões com salário informado.")
    return " ".join(frases)


# Números que o PDF mostra em cards (pdf_analitico.renderizar). O texto não os repete, salvo para
# uma comparação (revisão de 01/10/2026, itens 1, 2 e 8).
CARDS = ("panorama.saldo", "panorama.taxa_mes", "panorama.admissoes", "panorama.desligamentos",
         "panorama.estoque", "panorama.ano_anterior.admissoes", "panorama.ano_anterior.desligamentos",
         "panorama.decomposicao.variacao_admissoes", "panorama.decomposicao.variacao_desligamentos",
         "perfil.sexo.homem.participacao_admissoes", "perfil.sexo.mulher.participacao_admissoes",
         "salario.mediana", "salario.variacao_nominal_mediana")
# Dos cards, os que nem para comparação entram no texto (o card já basta). O saldo e as
# participações por sexo podem aparecer quando sustentam uma comparação.
SO_NOS_CARDS = set(CARDS) - {"panorama.saldo", "perfil.sexo.homem.participacao_admissoes",
                             "perfil.sexo.mulher.participacao_admissoes"}


def numeros_nos_cards(fatos: dict) -> list[str]:
    return [i for i in CARDS if i in fatos["numeros"]]


def numeros_do_texto(fatos: dict) -> list[str]:
    """Ids que o texto pode citar; o resto da tabela `numeros` fica nas tabelas e nos cards (o
    texto interpreta, a tabela detalha). Número fora desta lista gera aviso de estilo, não
    reprovação."""
    grupamentos = fatos.get("setorial", {}).get("grupamentos", {})
    destaques = {(grupamentos.get(g, {}).get("saldo") or {}).get("id")
                 for g in fatos.get("setorial", {}).get("destaques", [])}
    ids = []
    for i in fatos["numeros"]:
        campo = i.rsplit(".", 1)[-1]
        if i in SO_NOS_CARDS:
            continue
        if (i in destaques or i == "setorial.fora_dos_destaques.saldo" or i.startswith("selic.")
                or (i.startswith("pix.") and (campo.startswith("variacao_") or campo.endswith("_pp")))
                or (i.startswith("panorama.") and ".faixa_historica." not in i)
                or (i.startswith("desagregacao.") and campo in ("saldo", "saldo_restante", "saldo_ano_anterior"))
                or (i.startswith("perfil.") and campo in ("saldo", "participacao_admissoes",
                                                          "participacao_admissoes_ano_anterior"))
                or (i.startswith("salario.") and campo in ("mediana", "mediana_ano_anterior", "variacao_nominal_mediana"))):
            ids.append(i)
    return ids


def markdown(boletim: Boletim, fatos: dict) -> str:
    md = [f"# {boletim.titulo}", "", boletim.sintese, ""]
    for titulo, paragrafos in boletim.secoes():
        if paragrafos:
            md += [f"## {titulo}", "", *[p + "\n" for p in paragrafos]]
    md += [tabelas(fatos), complementares(fatos)]
    if boletim.pontos_de_atencao:  # ao final, antes da nota (revisão de 01/10/2026)
        md += ["## Pontos de atenção", ""] + [f"- {p}" for p in boletim.pontos_de_atencao] + [""]
    md += ["## Nota metodológica", "", nota_metodologica(fatos), ""]
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


def avisos(boletim: Boletim, fatos: dict) -> list[dict]:
    """Estilo e números que deveriam ficar só nas tabelas."""
    ids = numeros_do_texto(fatos)
    return avisos_de_estilo(boletim.texto()) + numeros_de_tabela(
        boletim.texto(), {i: fatos["numeros"][i] for i in ids}, fatos["numeros"], rotulos_dos_fatos(fatos))


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def _fatos_para_prompt(f: dict) -> str:
    """Os fatos, com os ids citáveis no texto e os que já estão nos cards. O Pix voltou ao prompt
    em 01/10/2026 (seção "Sinais da atividade econômica", com regras próprias)."""
    return _json({**{k: v for k, v in f.items() if k != "hash"},
                  "numeros_do_texto": numeros_do_texto(f), "numeros_nos_cards": numeros_nos_cards(f)})


# Calibrado em 29/09/2026 (flows/calibracao.py, 130 afirmações de 7 competências, peso 3 para
# falso positivo): com 0,6, nenhuma afirmação falsa passou em três rodadas; com 0,5, duas numa delas.
LIMIAR_AFIRMACAO = 0.6   # abaixo disso, a afirmação vai destacada para a revisão humana
LIMIAR_TRIAGEM = 0.6     # confiança mínima do Jev para descartar uma dúvida como "nenhuma"
MAX_ADVISOR = 2
def _numeros_de(fatos: dict, ids) -> dict:
    return {i: fatos["numeros"][i] for i in ids if i in fatos["numeros"]}


def _contexto_de_leitura(fatos: dict) -> dict:
    """Gatilhos, destaques e posição na faixa histórica (total e grupamentos): o que o Jev precisa
    para saber se os fatos já respondem a uma dúvida ou sustentam uma afirmação."""
    setorial = fatos.get("setorial", {})
    return {"gatilhos": fatos.get("gatilhos"), "destaques": setorial.get("destaques"),
            "posicoes_na_faixa_historica": {
                "total": fatos.get("panorama", {}).get("sazonalidade", {}).get("posicao"),
                **{g: it.get("sazonalidade", {}).get("posicao") for g, it in setorial.get("grupamentos", {}).items()}}}


def triar_duvida(ex: ia.Execucao, duvida: Duvida, fatos: dict) -> dict:
    """O Jev classifica a dúvida (não se confia no rótulo do próprio LLM)."""
    estado = {"duvida": duvida.pergunta, "por_que": duvida.por_que, "fatos_relacionados": _numeros_de(fatos, duvida.ids),
              "contexto": _contexto_de_leitura(fatos),
              "municipio": fatos["territorio"]["nome"], "competencia": fatos["rotulos"]["competencia"]}
    r = ex.decidir(estado, {"tipo": {
        "type": "choice", "instructions": "Que tipo de resposta essa dúvida exige?",
        "criteria": {"fora_dos_fatos": "Informação que os dados não trazem (acontecimentos, obras, empresas, deslocamentos).",
                     "metodo": "Saber como ler ou comparar os dados (estatística, conceito do CAGED).",
                     "nenhuma": "Os fatos relacionados ou o contexto já respondem, ou a dúvida não muda o texto."}}})
    tipo = r.get("tipo") or {}
    return {"pergunta": duvida.pergunta, "tipo_llm": duvida.tipo, "tipo_jev": tipo.get("choice"),
            "confianca_jev": tipo.get("confidence"), "probabilidades": tipo.get("probabilities")}


def julgar_afirmacoes(ex: ia.Execucao, boletim: Boletim, fatos: dict) -> list[dict]:
    """O Jev julga se os fatos citados sustentam cada afirmação interpretativa do texto."""
    if not boletim.afirmacoes:
        return []
    contexto = _contexto_de_leitura(fatos)
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
          refazer: bool = False, post_decisoes=None) -> dict:
    """Gera (ou reaproveita) o boletim com IA de um JSON de fatos. Devolve o resultado gravado."""
    texto_errado = {p: m for p, m in modelos.items() if p != "juiz" and e_modelo_de_decisao(m)}
    if texto_errado:
        raise ValueError(f"Modelos de decisão não redigem texto: {texto_errado}. Use-os como juiz.")
    territorio, competencia = fatos["territorio"]["codigo"], fatos["competencia"]
    chave = fatos["hash"][:16]
    pasta = cfg.pasta / "boletins" / f"{territorio}_{competencia}" / chave
    arquivo = pasta / "resultado.json"
    if arquivo.exists() and not refazer:
        resultado = json.loads(arquivo.read_text(encoding="utf-8"))
        resultado["reaproveitado"] = True
        resultado["pasta"] = str(pasta)
        return resultado
    # Refazer na mesma pasta (mesmo hash dos fatos): o que já foi aprovado ou enviado não se
    # sobrescreve; o que estava em revisão recomeça (ver _limpar_revisao_anterior).
    estado_anterior = pasta / "estado.json"
    if estado_anterior.exists():
        status = json.loads(estado_anterior.read_text(encoding="utf-8")).get("status")
        if status in ("aprovado", "enviado"):
            raise ValueError(f"O boletim em {pasta} já está '{status}': não se gera de novo por cima dele.")

    criar_modelo = criar_modelo or (lambda papel: ia.modelo_openrouter(cfg, modelos[papel], papel))
    agentes = criar_agentes(criar_modelo)
    contexto = Contexto(fatos)
    decisoes: list[dict] = []
    with ia.Execucao(cfg, modelos, precos=precos, registro=registro,
                     territorio=territorio, competencia=competencia) as ex:
        if post_decisoes:
            ex.post_decisoes = post_decisoes
        base = _fatos_para_prompt(fatos)
        analise = ex.rodar(agentes["analista"], "analista", f"Fatos do mês (JSON):\n{base}", deps=contexto)
        orientacoes, fora_dos_fatos = [], []
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
                try:
                    o: Orientacao = ex.rodar(agentes["advisor"], "advisor",
                                             f"Dúvida: {d.pergunta}\nPor quê: {d.por_que}\n"
                                             f"Fatos relacionados: {_json(_numeros_de(fatos, d.ids))}")
                    orientacoes.append({"pergunta": d.pergunta, **o.model_dump()})
                except UnexpectedModelBehavior as e:  # advisor é ajuda, não requisito
                    decisoes.append({"tipo": "advisor_falhou", "pergunta": d.pergunta, "erro": str(e)[:200]})
            elif tipo == "fora_dos_fatos":
                fora_dos_fatos.append(d.pergunta)

        extras = ""
        if orientacoes:
            extras += "\n\nOrientações de método do advisor (siga-as; não cite o advisor):\n" + _json(orientacoes)
        if fora_dos_fatos:
            # Escopo fechado nos fatos: o que exigiria informação externa não é afirmado.
            extras += ("\n\nAssuntos que os fatos não respondem (NÃO afirme nada sobre eles, nem como "
                       "possibilidade):\n" + _json(fora_dos_fatos))
        pedido = (f"Fatos do mês (JSON):\n{base}\n\nAnálise do analista (JSON):\n{analise.model_dump_json(indent=2)}"
                  + extras)
        boletim: Boletim = ex.rodar(agentes["redator"], "redator", pedido, deps=contexto)
        estilo = avisos(boletim, fatos)
        revisor_falhou = None
        try:
            parecer: Parecer = ex.rodar(agentes["revisor"], "revisor",
                                        f"Fatos completos (JSON):\n{base}\n\nBoletim (JSON):\n{boletim.model_dump_json(indent=2)}\n\n"
                                        f"Avisos de estilo do verificador:\n{_json(estilo)}")
        except UnexpectedModelBehavior as e:
            # O revisor é uma camada a mais, não um requisito: o verificador e o juiz continuam
            # valendo, e a falha vai destacada para a revisão humana.
            revisor_falhou = str(e)[:300]
            parecer = Parecer(problemas=[], resumo=f"REVISOR AUTOMÁTICO FALHOU ({revisor_falhou}); revise com atenção redobrada.")
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
        "avisos_de_estilo": avisos(boletim, fatos),
        "afirmacoes_nao_sustentadas": [a for a in afirmacoes if not a["sustentada"]],
        "orientacoes_do_advisor": orientacoes,
        "fora_dos_fatos": fora_dos_fatos,  # dúvidas que exigiriam informação externa: não afirmadas
        "decisoes": decisoes,  # registro de decisões (3b-2): triagens e julgamentos
        "parecer_revisor": parecer.model_dump(),
        "revisor_falhou": revisor_falhou,
        "analise": analise.model_dump(),
        "boletim": {**boletim.model_dump(), "nota_metodologica": nota_metodologica(fatos)},
    }
    pasta.mkdir(parents=True, exist_ok=True)
    _limpar_revisao_anterior(pasta)
    (pasta / "fatos.json").write_text(_json(fatos) + "\n", encoding="utf-8")
    (pasta / "boletim.md").write_text(markdown(boletim, fatos), encoding="utf-8")
    arquivo.write_text(_json(resultado) + "\n", encoding="utf-8")
    resultado["pasta"] = str(pasta)
    return resultado


def _limpar_revisao_anterior(pasta: Path) -> None:
    """Um texto novo invalida o PDF e o estado de revisão da versão anterior: sem isso, o
    `entrega_ia.py revisar` reenviaria o PDF antigo (ele só gera o PDF se não existir) e a
    aprovação valeria para bytes que ninguém releu."""
    for antigo in [*pasta.glob("boletim-ia-*.pdf"), pasta / "estado.json"]:
        antigo.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser(description="Gera o boletim com IA (F19); fica aguardando aprovação.")
    ap.add_argument("territorio")
    ap.add_argument("competencia")
    ap.add_argument("--warehouse", default="/data/warehouse/caged.duckdb")
    ap.add_argument("--refazer", action="store_true", help="gera de novo mesmo com resultado para estes fatos")
    ap.add_argument("--sem-indicadores", action="store_true", help="não busca Pix e Selic no Banco Central")
    a = ap.parse_args()
    cfg = ia.ConfigIA.do_ambiente()
    f = fatos_mod.gerar_fatos(Path(a.warehouse), a.territorio, a.competencia)
    if not a.sem_indicadores:
        import indicadores
        f = indicadores.anexar(f, Path(a.warehouse))
    try:
        r = gerar(f, cfg, modelos_do_ambiente(cfg), refazer=a.refazer)
    except ia.OrcamentoExcedido as e:
        raise SystemExit(f"Recusado pelo orçamento: {e}")
    except Exception as e:
        # 401/402/403 da OpenRouter: chave inválida, sem crédito ou limite da chave atingido
        # (o limite é vitalício e reajustado à mão todo mês).
        if any(c in str(e) for c in ("401", "402", "403")):
            raise SystemExit(f"A OpenRouter recusou a chamada ({e}). Confira a chave e o limite de crédito dela.")
        raise
    print(json.dumps({k: r[k] for k in ("situacao", "execucao", "modelos", "versoes_do_redator")}
                     | {"reaproveitado": r.get("reaproveitado", False), "problemas_verificador": len(r["verificador"]),
                        "rejeicoes": r.get("rejeicoes_do_verificador"), "avisos_de_estilo": len(r.get("avisos_de_estilo", [])),
                        "problemas_revisor": len(r["parecer_revisor"]["problemas"]), "pasta": r.get("pasta")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
