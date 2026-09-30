"""
Comparação prática de modelos redatores (F19 parte 6): o mesmo boletim, com os mesmos fatos,
escrito por modelos diferentes, com tudo o mais igual (analista, revisor, advisor e juiz fixos,
sem tickets). Mede o que dá para medir por código e prepara os textos ÀS CEGAS
para a leitura humana, que decide o que a métrica não pega (clareza, hierarquia, tom).

Saída em /data/ia/comparacao/<data>/:
- leitura.md:  os textos com rótulos embaralhados (A, B, C...) e a rubrica. Leia e dê as notas ANTES
               de abrir os outros arquivos.
- metricas.md: rejeições do verificador, avisos de estilo, afirmações não sustentadas, problemas
               graves do revisor, versões, custo real, tempo e palavras, por rótulo.
- gabarito.json: rótulo -> modelo.
Os custos vão para o registro real (/data/ia/custos.jsonl): o orçamento do mês enxerga tudo.

Uso:
    python flows/comparacao_modelos.py 280480 202606 202607 \\
        --redatores google/gemini-3.7-flash anthropic/claude-sonnet-5.5 z-ai/glm-5.3-flash
"""

import argparse
import json
import random
import string
import time
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import boletim_ia
import fatos as fatos_mod
import ia
import indicadores

RUBRICA = """\
Para cada texto, notas de 1 a 5:
- fidelidade: diz só o que os fatos sustentam, sem causa inventada;
- hierarquia: o principal vem primeiro; o secundário é resumido;
- clareza: um gestor entende em uma leitura;
- tom e estilo: técnico, direto, sem jargão de IA.
E, por competência, qual texto você enviaria como está (ou com menos edição).
"""


def custo_da_execucao(registro: ia.RegistroCustos, execucao: str) -> Decimal:
    return sum((Decimal(l["custo_usd"]) for l in registro._linhas()
                if l.get("execucao") == execucao and l["tipo"] == "chamada"), Decimal(0))


def comparar(warehouse: Path, territorio: str, competencias: list[str], redatores: list[str], cfg: ia.ConfigIA,
             semente: int = 7) -> Path:
    base_modelos = boletim_ia.modelos_do_ambiente(cfg)
    faltando = [m for m in redatores if m not in cfg.modelos_permitidos]
    if faltando:
        raise ValueError(f"Fora de IA_MODELOS_PERMITIDOS: {faltando}")
    dia = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")
    pasta = cfg.pasta / "comparacao" / dia
    pasta.mkdir(parents=True, exist_ok=True)
    cfg_isolado = replace(cfg, pasta=pasta / "execucoes")  # resultados e tickets à parte...
    registro, precos = ia.RegistroCustos(cfg.pasta), ia.Precos(cfg.pasta)  # ...custo no registro real
    sorteio = random.Random(semente)
    leitura = [f"# Comparação de redatores (às cegas), {dia}", "", RUBRICA]
    metricas, gabarito = [], {}
    for comp in competencias:
        f = indicadores.anexar(fatos_mod.gerar_fatos(warehouse, territorio, comp), warehouse)
        ordem = redatores[:]
        sorteio.shuffle(ordem)
        leitura += ["", f"## {f['rotulos']['competencia']}", ""]
        for letra, redator in zip(string.ascii_uppercase, ordem):
            rotulo = f"{comp}-{letra}"
            gabarito[rotulo] = redator
            modelos = {**base_modelos, "redator": redator}
            inicio = time.monotonic()
            try:
                r = boletim_ia.gerar(f, cfg_isolado, modelos, precos=precos, registro=registro, refazer=True, sem_tickets=True)
            except Exception as e:  # uma geração que falha é um resultado da comparação, não o fim dela
                metricas.append({"rotulo": rotulo, "situacao": f"falhou: {type(e).__name__}"})
                leitura += [f"### Texto {rotulo}", "", "(a geração falhou)", ""]
                print(f"{rotulo}: falhou ({type(e).__name__})", flush=True)
                continue
            segundos = round(time.monotonic() - inicio)
            b = r["boletim"]
            texto = Path(r["pasta"]) / "boletim.md"
            leitura += [f"### Texto {rotulo}", "", texto.read_text(encoding="utf-8").split("## Tabelas")[0], ""]
            metricas.append({
                "rotulo": rotulo, "situacao": r["situacao"],
                "numeros_rejeitados": sum(len(x) for x in r["rejeicoes_do_verificador"]),
                "problemas_finais_do_verificador": len(r["verificador"]),
                "avisos_de_estilo": len(r["avisos_de_estilo"]),
                "afirmacoes": len(b.get("afirmacoes", [])),
                "afirmacoes_nao_sustentadas": len(r["afirmacoes_nao_sustentadas"]),
                "graves_do_revisor": sum(1 for p in r["parecer_revisor"]["problemas"] if p["gravidade"] == "grave"),
                "revisor_falhou": bool(r.get("revisor_falhou")),
                "versoes": r["versoes_do_redator"],
                "custo_usd": str(round(custo_da_execucao(registro, r["execucao"]), 4)),
                "segundos": segundos,
                "palavras": len(boletim_ia.Boletim(**b).texto().split()),
            })
            print(f"{rotulo}: {r['situacao']} em {segundos}s", flush=True)
    (pasta / "leitura.md").write_text("\n".join(leitura) + "\n", encoding="utf-8")
    cab = list(max(metricas, key=len))
    tabela = ["| " + " | ".join(cab) + " |", "|" + "---|" * len(cab)]
    tabela += ["| " + " | ".join(str(m.get(k, "")) for k in cab) + " |" for m in metricas]
    (pasta / "metricas.md").write_text("# Métricas por texto (abra depois de dar as notas)\n\n" + "\n".join(tabela) + "\n",
                                       encoding="utf-8")
    (pasta / "gabarito.json").write_text(json.dumps(gabarito, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return pasta


def main():
    ap = argparse.ArgumentParser(description="Compara modelos redatores às cegas (F19 parte 6).")
    ap.add_argument("territorio")
    ap.add_argument("competencias", nargs="+")
    ap.add_argument("--redatores", nargs="+", required=True)
    ap.add_argument("--warehouse", default="/data/warehouse/caged.duckdb")
    a = ap.parse_args()
    pasta = comparar(Path(a.warehouse), a.territorio, a.competencias, a.redatores, ia.ConfigIA.do_ambiente())
    print(f"Leia {pasta}/leitura.md e dê as notas antes de abrir metricas.md e gabarito.json.")


if __name__ == "__main__":
    main()
