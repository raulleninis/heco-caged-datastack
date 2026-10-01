"""
Revisão, aprovação e envio do boletim com IA (F19 parte 5). Nada aqui é automático.

    boletim_ia.py (gera)          -> resultado "aguardando_aprovacao"
    entrega_ia.py revisar  T C    -> PDF + relatório de revisão SÓ para os administradores
                                     (secrets/destinatarios_admin.txt); estado "em_revisao"
    entrega_ia.py aprovar  T C --por "Nome"
                                  -> registra quem aprovou, quando e o sha256 do PDF revisado
    entrega_ia.py enviar   T C    -> arquiva e envia à lista principal o MESMO PDF

Garantias:
- O PDF é gerado UMA vez, na revisão. O que vai para a lista é exatamente o que os
  administradores leram: o envio confere o sha256 do PDF com o registrado na aprovação. (O
  fpdf grava a data de criação no arquivo; gerar de novo mudaria os bytes. Por isso o PDF não
  leva a marca "rascunho": ela vai só no e-mail aos administradores.)
- Resultado reprovado no verificador não pode ser revisado nem aprovado: gere de novo.
- O envio à lista usa as mesmas garantias da F15 (arquivo.py): estado no repositório do
  arquivo, com a chave "ia-AAAAMM"; "enviando" que não virou "enviado" é órfão e não se
  reenvia sozinho. O boletim automático da F15 não é afetado.
- O estado de revisão e aprovação fica ao lado do resultado (/data/ia/boletins/.../estado.json).

Uso:
    python flows/entrega_ia.py revisar 280480 202607
    python flows/entrega_ia.py aprovar 280480 202607 --por "Nome de quem aprovou"
    python flows/entrega_ia.py enviar  280480 202607
"""

import argparse
import json
import os
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from pathlib import Path

from pdf_analitico import gerar_pdf as gerar_pdf_analitico

import boletim
from alertas import _logger, notificar
from arquivo import agora, sha256
from entrega import Config, EnvioInterrompido, abrir_smtp, ler_destinatarios

PASTA_IA = Path(os.environ.get("IA_DIR", "/data/ia"))
ADMINS = Path(os.environ.get("DESTINATARIOS_ADMIN_ARQUIVO", "/secrets/destinatarios_admin.txt"))
AVISO_IA = ("Texto produzido com apoio de IA a partir de dados processados automaticamente e revisado antes "
            "da publicação.")


class RevisaoRecusada(RuntimeError):
    """O resultado não está em condição de seguir para a etapa pedida."""


def chave(competencia: str) -> str:
    return f"ia-{competencia}"


# --- resultado e estado ------------------------------------------------------------------------

def pasta_do_resultado(territorio: str, competencia: str, base: Path = PASTA_IA) -> Path:
    """A geração mais recente do boletim com IA para o território e a competência."""
    pastas = [p.parent for p in (base / "boletins" / f"{territorio}_{competencia}").glob("*/resultado.json")]
    if not pastas:
        raise RevisaoRecusada(f"Nenhum boletim com IA gerado para {territorio} em {competencia}.")
    return max(pastas, key=lambda p: json.loads((p / "resultado.json").read_text(encoding="utf-8"))["gerado_em"])


def ler_estado(pasta: Path) -> dict:
    arq = pasta / "estado.json"
    return json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {"status": "aguardando_revisao"}


def gravar_estado(pasta: Path, **campos) -> dict:
    estado = {**ler_estado(pasta), **campos}
    (pasta / "estado.json").write_text(json.dumps(estado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return estado


# --- PDF -----------------------------------------------------------------------------------------

def gerar_pdf(pasta: Path) -> Path:
    """Gera a apresentação; revisão, aprovação e envio preservam o mesmo PDF."""
    return gerar_pdf_analitico(pasta, aviso_ia=AVISO_IA)


# --- e-mail --------------------------------------------------------------------------------------

def _mensagem(cfg: Config, para: str, assunto: str, corpo: list[str], pdf: bytes, nome_pdf: str,
              extra: tuple[str, bytes] | None = None, lista: bool = False) -> EmailMessage:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = cfg.remetente, para, assunto
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=parseaddr(cfg.remetente)[1].rpartition("@")[2] or None)
    if cfg.responder_para:
        msg["Reply-To"] = cfg.responder_para
    if lista:
        sair = cfg.sair_da_lista
        msg["List-Unsubscribe"] = f"<{sair}>" if sair.startswith("http") else f"<mailto:{sair.removeprefix('mailto:')}>"
        corpo = corpo + ["", f"Para deixar de receber: {sair.removeprefix('mailto:')}"]
    msg.set_content("\n".join(corpo))
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=nome_pdf)
    if extra:
        msg.add_attachment(extra[1], maintype="text", subtype="plain", filename=extra[0])
    return msg


def _relatorio_de_revisao(r: dict) -> str:
    linhas = [f"Situação: {r['situacao']} | versões do redator: {r['versoes_do_redator']} | modelos: {r['modelos']}"]
    if r.get("revisor_falhou"):
        linhas += ["ATENÇÃO: o revisor automático falhou nesta geração; só o verificador e o juiz conferiram o texto."]
    linhas += [
              "", "PARECER DO REVISOR (modelo):", r["parecer_revisor"]["resumo"], ""]
    for p in r["parecer_revisor"]["problemas"]:
        linhas.append(f"- [{p['gravidade']}/{p['tipo']}] {p['trecho']}  ->  {p['sugestao']}")
    linhas += ["", f"VERIFICADOR DE NÚMEROS: {len(r['verificador'])} problema(s)"]
    linhas += [f"- {p['tipo']}: {p.get('numero')} em ...{p['trecho']}..." for p in r["verificador"]]
    linhas += ["", f"AVISOS DE ESTILO: {len(r.get('avisos_de_estilo', []))}"]
    linhas += [f"- {a['motivo']}: ...{a['trecho']}..." for a in r.get("avisos_de_estilo", [])]
    nao = r.get("afirmacoes_nao_sustentadas", [])
    linhas += ["", f"AFIRMAÇÕES QUE O JUIZ (Jev) NÃO VIU SUSTENTADAS PELOS FATOS: {len(nao)}  (confira estas primeiro)"]
    linhas += [f"- p={a['probabilidade']}: {a['texto']}  [ids: {', '.join(a['ids'])}]" for a in nao]
    if r.get("orientacoes_do_advisor"):
        linhas += ["", "ORIENTAÇÕES DO ADVISOR (dúvidas de método):"]
        linhas += [f"- {o['pergunta']} -> {o['resposta']} (confiança {o['confianca']})" for o in r["orientacoes_do_advisor"]]
    if r.get("respostas_humanas"):
        linhas += ["", "RESPOSTAS HUMANAS A TICKETS USADAS:"]
        linhas += [f"- {q['pergunta']} -> {q['resposta']} ({q.get('respondido_por', '')})" for q in r["respostas_humanas"]]
    return "\n".join(linhas) + "\n"


# --- etapas --------------------------------------------------------------------------------------

def revisar(territorio: str, competencia: str, *, cfg: Config | None = None, smtp_factory=None,
            base: Path = PASTA_IA, admins: Path = ADMINS) -> Path:
    """Gera o PDF (uma vez) e envia aos administradores, com o relatório de revisão."""
    cfg = cfg or Config.do_ambiente()
    pasta = pasta_do_resultado(territorio, competencia, base)
    r = json.loads((pasta / "resultado.json").read_text(encoding="utf-8"))
    if r["situacao"] != "aguardando_aprovacao":
        raise RevisaoRecusada(f"Resultado em '{r['situacao']}': gere de novo (boletim_ia.py --refazer) antes de revisar.")
    estado = ler_estado(pasta)
    if estado["status"] in ("aprovado", "enviado"):
        raise RevisaoRecusada(f"Este boletim já está '{estado['status']}'.")
    pdf = pasta / f"boletim-ia-{competencia}.pdf"
    if not pdf.exists():
        gerar_pdf(pasta)
    destinatarios = ler_destinatarios(admins)
    nome = boletim.nome_competencia(competencia)
    corpo = [
        f"RASCUNHO PARA REVISÃO do boletim com análise de {nome} (território {territorio}).",
        "Só os administradores receberam. Nada foi arquivado nem enviado à lista.",
        "",
        "O relatório anexo traz o parecer do revisor automático, o verificador de números, os avisos de",
        "estilo e as afirmações a conferir. Para aprovar ESTA versão (o mesmo PDF irá para a lista):",
        f"    python flows/entrega_ia.py aprovar {territorio} {competencia} --por \"Seu nome\"",
        "Para pedir outra versão: python flows/boletim_ia.py ... --refazer, e revisar de novo.",
    ]
    relatorio = ("revisao.txt", _relatorio_de_revisao(r).encode("utf-8"))
    abrir = smtp_factory or (lambda: abrir_smtp(cfg))
    with abrir() as smtp:
        for d in destinatarios:
            smtp.send_message(_mensagem(cfg, d, f"[REVISÃO] Boletim com análise - {nome}", corpo,
                                        pdf.read_bytes(), pdf.name, extra=relatorio))
    gravar_estado(pasta, status="em_revisao", enviado_admins_em=agora(), sha256_pdf=sha256(pdf),
                  admins=len(destinatarios), pasta_resultado=str(pasta))
    _logger().info(f"Boletim com IA {competencia} enviado a {len(destinatarios)} administrador(es) para revisão.")
    return pasta


def aprovar(territorio: str, competencia: str, por: str, *, base: Path = PASTA_IA) -> dict:
    """Registra a aprovação da versão que os administradores receberam."""
    if not por.strip():
        raise RevisaoRecusada("Informe quem aprovou (--por).")
    pasta = pasta_do_resultado(territorio, competencia, base)
    estado = ler_estado(pasta)
    if estado["status"] != "em_revisao":
        raise RevisaoRecusada(f"Só se aprova o que está em revisão; este está em '{estado['status']}'.")
    pdf = pasta / f"boletim-ia-{competencia}.pdf"
    if sha256(pdf) != estado["sha256_pdf"]:
        raise RevisaoRecusada("O PDF mudou depois da revisão: revise de novo antes de aprovar.")
    return gravar_estado(pasta, status="aprovado", aprovado_por=por.strip(), aprovado_em=agora())


def enviar(territorio: str, competencia: str, *, cfg: Config | None = None, smtp_factory=None,
           base: Path = PASTA_IA) -> str:
    """Arquiva e envia à lista principal o PDF aprovado. Idempotente (chave ia-AAAAMM)."""
    log = _logger()
    cfg = cfg or Config.do_ambiente()
    cfg.exigir(teste=False)
    pasta = pasta_do_resultado(territorio, competencia, base)
    estado = ler_estado(pasta)
    if estado["status"] not in ("aprovado", "enviado"):
        raise RevisaoRecusada(f"Só se envia o que foi aprovado; este está em '{estado['status']}'.")
    pdf_local = pasta / f"boletim-ia-{competencia}.pdf"
    if sha256(pdf_local) != estado["sha256_pdf"]:
        raise RevisaoRecusada("O PDF não é o que foi aprovado (sha256 diferente). Nada enviado.")

    arquivo = cfg.arquivo
    arquivo.sincronizar()
    k = chave(competencia)
    registro = arquivo.envios().get(k, {})
    if registro.get("status") == "enviado":
        log.info(f"{k} já foi enviado em {registro.get('enviado_em')}; nada a fazer.")
        return "ja_enviado"
    if registro.get("status") == "enviando":
        log.error(f"{k} está órfão (enviando); sem reenvio automático.")
        return "orfao"

    destinatarios = ler_destinatarios(cfg.destinatarios_arquivo)
    arquivado = arquivo.arquivar_extra(competencia, pdf_local, f"arquivo: boletim com IA de {competencia}")
    corpo_pdf = arquivado.read_bytes()
    arquivo.gravar_estado(k, status="enviando", iniciado_em=agora(), enviado_em=None, sha256_boletim=sha256(arquivado),
                          aprovado_por=estado["aprovado_por"], aprovado_em=estado["aprovado_em"],
                          destinatarios_total=len(destinatarios), destinatarios_enviados=0)
    nome = boletim.nome_competencia(competencia)
    corpo = [f"Segue o boletim com análise do emprego formal de {nome}.",
             "Os números são do Novo CAGED (PDET/MTE) e podem ser revisados em competências futuras.", "", AVISO_IA]
    if cfg.site_url:
        corpo += ["", f"Arquivo dos boletins (exige login): {cfg.site_url}"]
    enviados, recusados = 0, 0
    abrir = smtp_factory or (lambda: abrir_smtp(cfg))
    try:
        with abrir() as smtp:
            for d in destinatarios:
                try:
                    smtp.send_message(_mensagem(cfg, d, f"Boletim com análise - {nome}", corpo, corpo_pdf,
                                                arquivado.name, lista=True))
                except smtplib.SMTPRecipientsRefused:
                    recusados += 1
                    continue
                enviados += 1
    except Exception as e:  # noqa: BLE001 — qualquer queda vira órfão explícito
        erro = f"{type(e).__name__}: {e}"[:300]
        try:
            arquivo.gravar_estado(k, destinatarios_enviados=enviados, erro=erro)
        except Exception as e2:  # noqa: BLE001
            log.error(f"Não consegui gravar o erro no envios.json: {e2}")
        notificar("CAGED: envio do boletim com IA INTERROMPIDO",
                  f"{k}: parou após {enviados} de {len(destinatarios)} ({erro}). Não será reenviado sozinho.",
                  prioridade="urgent")
        raise EnvioInterrompido(f"{k}: {enviados}/{len(destinatarios)} enviados. {erro}") from e
    arquivo.gravar_estado(k, status="enviado", enviado_em=agora(), destinatarios_enviados=enviados,
                          destinatarios_recusados=recusados, erro=None)
    gravar_estado(pasta, status="enviado", enviado_em=agora(), destinatarios=enviados)
    log.info(f"{k} enviado a {enviados} destinatário(s), {recusados} recusado(s).")
    return "enviado"


def main():
    ap = argparse.ArgumentParser(description="Revisão, aprovação e envio do boletim com IA (F19 parte 5).")
    ap.add_argument("acao", choices=["revisar", "aprovar", "enviar"])
    ap.add_argument("territorio")
    ap.add_argument("competencia")
    ap.add_argument("--por", default="", help="quem aprovou (obrigatório em aprovar)")
    a = ap.parse_args()
    try:
        if a.acao == "revisar":
            print(f"Enviado aos administradores: {revisar(a.territorio, a.competencia)}")
        elif a.acao == "aprovar":
            e = aprovar(a.territorio, a.competencia, a.por)
            print(f"Aprovado por {e['aprovado_por']} em {e['aprovado_em']}.")
        else:
            print(enviar(a.territorio, a.competencia))
    except RevisaoRecusada as e:
        raise SystemExit(f"Recusado: {e}")


if __name__ == "__main__":
    main()
