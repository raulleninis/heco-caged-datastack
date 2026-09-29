"""
Boletim com IA (F19 parte 3): analista → redator → revisor, sobre os fatos da parte 1, dentro
das proteções da parte 2. Resultado fica AGUARDANDO APROVAÇÃO humana; nada é enviado aqui.

Fluxo fixo, sem agente decidindo chamar outro (docs/fatias/F19-boletim-com-ia.md):

1. fatos (flows/fatos.py), com hash. Mesmo hash e resultado já gerado: reaproveita, sem LLM
   (só gera de novo com --refazer).
2. analista: escolhe até 5 destaques e até 3 hipóteses a investigar, citando ids de `numeros`.
3. redator: escreve o boletim. O verificador de números é o seu output_validator: número fora
   dos fatos gera UMA nova tentativa; na última, o texto é aceito e segue com o relatório de
   problemas para a revisão humana (em vez de abortar e perder o que foi pago).
4. revisor (outra família de modelo): parecer sobre causalidade, fontes, rótulos, identificação.
   Havendo problema grave, o redator faz uma segunda versão, verificada de novo.
5. grava fatos.json, resultado.json e boletim.md, com situação `aguardando_aprovacao` ou
   `reprovado_no_verificador`.

Pior caso de requisições: analista 2 + redator 2 + revisor 1 + redator 2 = 7, dentro do
request_limit de 8 da Execucao. O pesquisador (evidências externas) entra na parte 4.

Uso:
    python flows/boletim_ia.py 280480 202607 [--refazer] [--warehouse ...]
"""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext

import fatos as fatos_mod
import ia
from verificador import verificar_texto

# --- saídas tipadas ---------------------------------------------------------------------------


class Destaque(BaseModel):
    tema: str
    ids: list[str] = Field(min_length=1, description="ids da tabela `numeros` que sustentam o destaque")
    por_que: str = Field(description="qual regra ou gatilho o torna destaque")


class HipoteseAInvestigar(BaseModel):
    tema: str
    pergunta: str
    escala: Literal["municipal", "regional", "estadual", "nacional"]


class Analise(BaseModel):
    destaques: list[Destaque] = Field(max_length=5)
    desagregacoes: list[str] = Field(default_factory=list, description="códigos de `desagregacao` a usar no texto")
    hipoteses_a_investigar: list[HipoteseAInvestigar] = Field(default_factory=list, max_length=3)


class Secao(BaseModel):
    titulo: str
    paragrafos: list[str]


class Hipotese(BaseModel):
    texto: str = Field(description="rotulada como hipótese; nunca como causa comprovada")
    apoio: list[str] = Field(default_factory=list, description="ids de `numeros` ou fontes citadas")


class Boletim(BaseModel):
    titulo: str
    sintese: str
    secoes: list[Secao]
    hipoteses: list[Hipotese] = Field(default_factory=list, max_length=3)
    limitacoes: list[str] = Field(default_factory=list)

    def texto(self) -> str:
        partes = [self.titulo, self.sintese]
        for s in self.secoes:
            partes += [s.titulo, *s.paragrafos]
        partes += [h.texto for h in self.hipoteses] + self.limitacoes
        return "\n".join(partes)

    def markdown(self) -> str:
        md = [f"# {self.titulo}", "", self.sintese, ""]
        for s in self.secoes:
            md += [f"## {s.titulo}", "", *[p + "\n" for p in s.paragrafos]]
        if self.hipoteses:
            md += ["## Hipóteses (não comprovadas)", ""] + [f"- {h.texto}" for h in self.hipoteses] + [""]
        if self.limitacoes:
            md += ["## Limitações", ""] + [f"- {l}" for l in self.limitacoes] + [""]
        return "\n".join(md)


class Problema(BaseModel):
    tipo: Literal["numero", "causalidade", "fonte", "rotulo", "identificacao", "estilo"]
    gravidade: Literal["grave", "menor"]
    trecho: str
    sugestao: str


class Parecer(BaseModel):
    problemas: list[Problema] = Field(default_factory=list)
    resumo: str


# --- instruções (resumo das regras de docs/boletim-ia/roteiro.md) -----------------------------

REGRAS = """\
Regras obrigatórias:
- Todo número que você escrever tem de estar na tabela `numeros` dos fatos, com o mesmo valor
  (formato brasileiro: 25.439; 0,33%; R$ 1.661,00). NUNCA calcule, some, subtraia ou derive
  números novos, nem diferenças de percentuais. Se um número não está nos fatos, não o use.
- Unidade de análise: o município. Região e UF são contexto, não explicação do município.
- Análise setorial pelos grandes grupamentos; desagregue só as atividades listadas em
  `desagregacao`. Nunca identifique, sugira ou insinue empresas ou estabelecimentos.
- Separe fato observado, evidência complementar e hipótese. Não atribua causa sem evidência;
  hipótese sempre rotulada como hipótese.
- Se o resultado está dentro da faixa histórica do mês, diga isso sem inventar explicação.
- Competência provisória: diga que o número ainda pode ser revisado.
- Salário: a mediana é a referência; a média só para comparação.
- Recortes marcados como base pequena não são interpretados.
"""

INSTRUCOES = {
    "analista": "Você é o analista de um boletim mensal de emprego formal (Novo CAGED). Recebe os fatos já "
                "calculados e escolhe o que merece destaque, seguindo os `gatilhos` e os `destaques` setoriais. "
                "Cada destaque cita ids da tabela `numeros`. Proponha no máximo 3 hipóteses a investigar, com a "
                "escala da evidência que as testaria.\n" + REGRAS,
    "redator": "Você redige, em português do Brasil, um boletim mensal de emprego formal de 3 a 4 páginas: "
               "síntese; panorama; desempenho setorial; contexto regional (município × região × UF); perfil das "
               "contratações; interpretação com no máximo 3 hipóteses. Tom técnico e claro.\n" + REGRAS,
    "revisor": "Você revisa um boletim de emprego formal escrito por outro modelo. Aponte problemas de: número "
               "que não confere com os fatos; linguagem causal sem evidência; hipótese não rotulada; fonte ou "
               "período ausente; qualquer identificação de empresa; estilo. Marque como grave o que não pode "
               "sair publicado. Não reescreva o texto.\n" + REGRAS,
}


def criar_agentes(criar_modelo) -> dict[str, Agent]:
    """Os três agentes. `criar_modelo(papel)` devolve o modelo de cada papel (OpenRouter em
    produção; FunctionModel nos testes)."""
    analista = Agent(criar_modelo("analista"), output_type=Analise, instructions=INSTRUCOES["analista"],
                     deps_type=dict, retries=1)
    redator = Agent(criar_modelo("redator"), output_type=Boletim, instructions=INSTRUCOES["redator"],
                    deps_type=dict, retries=1)
    revisor = Agent(criar_modelo("revisor"), output_type=Parecer, instructions=INSTRUCOES["revisor"], retries=1)

    @analista.output_validator
    def ids_existem(ctx: RunContext[dict], saida: Analise) -> Analise:
        faltando = sorted({i for d in saida.destaques for i in d.ids} - set(ctx.deps["numeros"]))
        if faltando and ctx.retry < ctx.max_retries:
            raise ModelRetry(f"Estes ids não existem na tabela `numeros`: {faltando}. Use só ids existentes.")
        return saida

    @redator.output_validator
    def numeros_conferem(ctx: RunContext[dict], saida: Boletim) -> Boletim:
        problemas = [p for p in verificar_texto(saida.texto(), ctx.deps["numeros"])
                     if p["tipo"] == "numero_fora_dos_fatos"]
        if problemas and ctx.retry < ctx.max_retries:
            lista = "; ".join(f"{p['numero']} em \"…{p['trecho']}…\"" for p in problemas[:15])
            raise ModelRetry("Estes números não estão na tabela `numeros` dos fatos (não calcule nem derive "
                             f"números): {lista}. Reescreva usando só valores da tabela.")
        return saida  # última tentativa: segue com o relatório para a revisão humana

    return {"analista": analista, "redator": redator, "revisor": revisor}


# --- orquestração --------------------------------------------------------------------------------

def modelos_do_ambiente(cfg: ia.ConfigIA) -> dict[str, str]:
    """IA_MODELO_<PAPEL>; sem eles: redator = 1º permitido, analista e revisor = último (outra
    família, se a lista tiver duas)."""
    if not cfg.modelos_permitidos:
        raise RuntimeError("IA_MODELOS_PERMITIDOS vazio: nenhum modelo pode rodar.")
    primeiro, ultimo = cfg.modelos_permitidos[0], cfg.modelos_permitidos[-1]
    return {
        "analista": os.environ.get("IA_MODELO_ANALISTA") or ultimo,
        "redator": os.environ.get("IA_MODELO_REDATOR") or primeiro,
        "revisor": os.environ.get("IA_MODELO_REVISOR") or ultimo,
    }


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def _fatos_para_prompt(f: dict) -> str:
    return _json({k: v for k, v in f.items() if k != "hash"})


def gerar(fatos: dict, cfg: ia.ConfigIA, modelos: dict[str, str], *, criar_modelo=None,
          precos: ia.Precos | None = None, registro: ia.RegistroCustos | None = None,
          refazer: bool = False) -> dict:
    """Gera (ou reaproveita) o boletim com IA de um JSON de fatos. Devolve o resultado gravado."""
    territorio, competencia = fatos["territorio"]["codigo"], fatos["competencia"]
    pasta = cfg.pasta / "boletins" / f"{territorio}_{competencia}" / fatos["hash"][:16]
    arquivo = pasta / "resultado.json"
    if arquivo.exists() and not refazer:
        resultado = json.loads(arquivo.read_text(encoding="utf-8"))
        resultado["reaproveitado"] = True
        resultado["pasta"] = str(pasta)
        return resultado

    criar_modelo = criar_modelo or (lambda papel: ia.modelo_openrouter(cfg, modelos[papel], papel))
    agentes = criar_agentes(criar_modelo)
    with ia.Execucao(cfg, modelos, precos=precos, registro=registro,
                     territorio=territorio, competencia=competencia) as ex:
        base = _fatos_para_prompt(fatos)
        analise: Analise = ex.rodar(agentes["analista"], "analista", f"Fatos do mês (JSON):\n{base}", deps=fatos)
        pedido = (f"Fatos do mês (JSON):\n{base}\n\nAnálise do analista (JSON):\n{analise.model_dump_json(indent=2)}\n\n"
                  "Evidências externas: nenhuma nesta versão. Não cite fontes externas nem acontecimentos.")
        boletim: Boletim = ex.rodar(agentes["redator"], "redator", pedido, deps=fatos)
        tabela = _json({"numeros": fatos["numeros"], "gatilhos": fatos["gatilhos"], "provisorio": fatos["provisorio"]})
        parecer: Parecer = ex.rodar(agentes["revisor"], "revisor",
                                    f"Fatos (tabela de números e gatilhos):\n{tabela}\n\nBoletim (JSON):\n{boletim.model_dump_json(indent=2)}")
        versoes = 1
        if any(p.gravidade == "grave" for p in parecer.problemas):
            boletim = ex.rodar(agentes["redator"], "redator",
                               f"{pedido}\n\nSua versão anterior (JSON):\n{boletim.model_dump_json(indent=2)}\n\n"
                               f"Problemas apontados pelo revisor (corrija os graves):\n{parecer.model_dump_json(indent=2)}",
                               deps=fatos)
            versoes = 2
        execucao_id = ex.id

    problemas = verificar_texto(boletim.texto(), fatos["numeros"])
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
        "parecer_revisor": parecer.model_dump(),
        "analise": analise.model_dump(),
        "boletim": boletim.model_dump(),
    }
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "fatos.json").write_text(_json(fatos) + "\n", encoding="utf-8")
    (pasta / "boletim.md").write_text(boletim.markdown(), encoding="utf-8")
    arquivo.write_text(_json(resultado) + "\n", encoding="utf-8")
    resultado["pasta"] = str(pasta)
    return resultado


def main():
    ap = argparse.ArgumentParser(description="Gera o boletim com IA (F19 parte 3); fica aguardando aprovação.")
    ap.add_argument("territorio")
    ap.add_argument("competencia")
    ap.add_argument("--warehouse", default="/data/warehouse/caged.duckdb")
    ap.add_argument("--refazer", action="store_true", help="gera de novo mesmo com resultado para estes fatos")
    a = ap.parse_args()
    cfg = ia.ConfigIA.do_ambiente()
    f = fatos_mod.gerar_fatos(Path(a.warehouse), a.territorio, a.competencia)
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
                        "problemas_revisor": len(r["parecer_revisor"]["problemas"]), "pasta": r.get("pasta")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
