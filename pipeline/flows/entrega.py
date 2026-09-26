"""
Entrega do boletim por e-mail, com arquivamento e envio idempotente (F15).

Ordem dentro de uma entrega (cada gravação de estado é um commit com push no
repositório do arquivo — ver arquivo.py):

    gera -> arquiva -> grava `enviando` -> envia -> grava `enviado`

Garantias:
- O estado vive no repositório do arquivo, não no warehouse (D03): apagar o
  .duckdb e reconstruí-lo NÃO reenvia nada.
- `enviando` que não virou `enviado` = o processo morreu no meio e ninguém
  sabe quem recebeu. NÃO se reenvia sozinho: alerta a cada run até alguém
  decidir a mão (ver "Resolver um envio órfão" no README). Duplicar e-mail
  para uma lista é pior que atrasá-lo.
- Um e-mail por destinatário (ninguém vê a lista), com List-Unsubscribe.
- O que se anexa são os bytes lidos DO ARQUIVO, os mesmos que o sha256 do
  envios.json descreve.
- Sem estado legível (repositório inacessível) não há envio: falha fechado.
- Só a competência MAIS RECENTE do mart é candidata a envio automático.
  Competências antigas (reconstrução do warehouse, backfill) nunca disparam
  e-mail; para enviar uma antiga, use o comando manual `enviar`.

Configuração toda por variável de ambiente (ver .env.example). Credenciais e a
lista de destinatários (dado pessoal — LGPD) ficam fora do git.

Uso manual:
    python flows/entrega.py teste [AAAAMM]   # só para EMAIL_TESTE; não arquiva nem registra
    python flows/entrega.py enviar AAAAMM    # envio real (idempotente)
    python flows/entrega.py arquivar 202001..202606 [202607 ...]
                                             # só gera e arquiva, sem e-mail nem estado de envio
"""

import os
import re
import smtplib
import ssl
import sys
import tempfile
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from pathlib import Path

import duckdb
from prefect import task

import boletim
from alertas import _logger, notificar
from arquivo import Arquivo, agora, sha256

WAREHOUSE_PATH = Path("/data/warehouse/caged.duckdb")
XLSX_MIME = ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ConfigIncompleta(RuntimeError):
    """Falta variável de ambiente necessária para entregar."""


class EnvioInterrompido(RuntimeError):
    """O envio parou no meio: fica um `enviando` órfão, sem reenvio automático."""


@dataclass
class Config:
    arquivo: Arquivo | None
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    remetente: str
    sair_da_lista: str
    email_teste: str
    destinatarios_arquivo: Path
    site_url: str
    warehouse: Path = WAREHOUSE_PATH
    responder_para: str = ""

    @classmethod
    def do_ambiente(cls) -> "Config":
        env = lambda k, padrao="": os.environ.get(k, padrao).strip()  # noqa: E731
        repo = env("ARQUIVO_REPO_URL")
        chave = env("ARQUIVO_DEPLOY_KEY", "/secrets/arquivo_deploy_key")
        arquivo = None
        if repo:
            arquivo = Arquivo(
                repo_url=repo,
                diretorio=Path(env("ARQUIVO_DIR", "/data/arquivo")),
                branch=env("ARQUIVO_BRANCH", "main"),
                deploy_key=Path(chave) if Path(chave).exists() else None,
            )
        return cls(
            arquivo=arquivo,
            smtp_host=env("SMTP_HOST"),
            smtp_port=int(env("SMTP_PORT", "587")),
            smtp_user=env("SMTP_USER"),
            smtp_password=os.environ.get("SMTP_PASSWORD", ""),
            remetente=env("EMAIL_REMETENTE"),
            sair_da_lista=env("EMAIL_SAIR_DA_LISTA"),
            email_teste=env("EMAIL_TESTE"),
            destinatarios_arquivo=Path(env("DESTINATARIOS_ARQUIVO", "/secrets/destinatarios.txt")),
            site_url=env("ARQUIVO_SITE_URL"),
            responder_para=env("EMAIL_RESPONDER_PARA"),
        )

    def exigir(self, teste: bool) -> None:
        faltam = [n for n, v in (
            ("SMTP_HOST", self.smtp_host), ("EMAIL_REMETENTE", self.remetente),
            ("EMAIL_SAIR_DA_LISTA", self.sair_da_lista),
        ) if not v]
        if teste and not self.email_teste:
            faltam.append("EMAIL_TESTE")
        if not teste and self.arquivo is None:
            faltam.append("ARQUIVO_REPO_URL")
        if faltam:
            raise ConfigIncompleta(f"Variáveis de ambiente ausentes: {', '.join(faltam)}")


# --------------------------------------------------------------------- e-mail

def ler_destinatarios(caminho: Path) -> list[str]:
    """Um endereço por linha; '#' comenta; repetidos e inválidos são descartados
    (inválidos só contados no log: o endereço é dado pessoal)."""
    if not caminho.exists():
        raise ConfigIncompleta(f"Lista de destinatários não encontrada em {caminho}")
    vistos, validos, invalidos = set(), [], 0
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.split("#", 1)[0].strip()
        if not linha:
            continue
        if not EMAIL_RE.match(linha):
            invalidos += 1
            continue
        if linha.lower() not in vistos:
            vistos.add(linha.lower())
            validos.append(linha)
    if invalidos:
        _logger().warning(f"{invalidos} linha(s) inválida(s) ignorada(s) em {caminho.name}")
    if not validos:
        raise ConfigIncompleta(f"Lista de destinatários vazia em {caminho}")
    return validos


def montar_mensagem(
    cfg: Config, destinatario: str, competencia: str, pdf: bytes, xlsx: bytes, teste: bool = False
) -> EmailMessage:
    nome = boletim.nome_competencia(competencia)
    sair = cfg.sair_da_lista
    if sair.startswith(("http://", "https://")):
        cabecalho_sair, texto_sair = f"<{sair}>", f"Para deixar de receber, acesse {sair}"
    else:
        sair = sair.removeprefix("mailto:")
        cabecalho_sair, texto_sair = f"<mailto:{sair}>", f"Para deixar de receber, escreva para {sair}."

    linhas = []
    if teste:
        linhas += ["ENVIO DE TESTE: só você recebeu; nada foi arquivado nem registrado.", ""]
    linhas += [
        f"Segue o boletim CAGED de {nome} para Nossa Senhora do Socorro/SE, com a planilha dos dados.",
        "Os números são do Novo CAGED (PDET/MTE) e podem ser revisados em competências futuras.",
    ]
    if cfg.site_url:
        linhas += ["", f"Arquivo dos boletins (exige login): {cfg.site_url}"]
    linhas += ["", texto_sair]

    msg = EmailMessage()
    msg["From"] = cfg.remetente
    msg["To"] = destinatario
    msg["Subject"] = ("[TESTE] " if teste else "") + f"Boletim CAGED - Nossa Senhora do Socorro/SE - {nome}"
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=parseaddr(cfg.remetente)[1].rpartition("@")[2] or None)
    msg["List-Unsubscribe"] = cabecalho_sair
    if cfg.responder_para:
        # O remetente (boletim@subdominio) não é uma caixa: sem isto, quem responde ao
        # boletim fala com ninguém.
        msg["Reply-To"] = cfg.responder_para
    msg.set_content("\n".join(linhas))
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=f"boletim-{competencia}.pdf")
    msg.add_attachment(xlsx, maintype=XLSX_MIME[0], subtype=XLSX_MIME[1], filename=f"planilha-{competencia}.xlsx")
    return msg


def abrir_smtp(cfg: Config) -> smtplib.SMTP:
    """Conexão SMTP autenticada. 465 = TLS direto; qualquer outra = STARTTLS
    obrigatório (sem TLS, falha). A porta 25 costuma estar bloqueada na saída
    das VMs da Oracle: use 587/465."""
    contexto = ssl.create_default_context()
    if cfg.smtp_port == 465:
        smtp = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=30, context=contexto)
    else:
        smtp = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30)
        smtp.starttls(context=contexto)
    if cfg.smtp_user:
        smtp.login(cfg.smtp_user, cfg.smtp_password)
    return smtp


# ------------------------------------------------------------------- entrega

def ultima_competencia(warehouse: Path) -> str | None:
    if not warehouse.exists():
        return None
    con = duckdb.connect(str(warehouse), read_only=True)
    try:
        existe = con.execute(
            "select 1 from information_schema.tables where table_name = 'mart_caged_mensal_grupamento'"
        ).fetchone()
        if not existe:
            return None
        valor = con.execute("select max(competencia_mov) from mart_caged_mensal_grupamento").fetchone()[0]
    finally:
        con.close()
    return None if valor is None else str(valor)


def entregar(competencia: str, *, teste: bool = False, cfg: Config | None = None, smtp_factory=None) -> str:
    """Entrega o boletim de 'competencia'. Devolve o desfecho:
    'teste' | 'enviado' | 'ja_enviado' | 'orfao'. Levanta EnvioInterrompido se
    o envio parar no meio, ConfigIncompleta se faltar configuração."""
    log = _logger()
    cfg = cfg or Config.do_ambiente()
    cfg.exigir(teste)
    abrir = smtp_factory or (lambda: abrir_smtp(cfg))

    if teste:
        with tempfile.TemporaryDirectory() as tmp:
            pdf, xlsx = boletim.gerar(cfg.warehouse, competencia, Path(tmp))
            msg = montar_mensagem(cfg, cfg.email_teste, competencia, pdf.read_bytes(), xlsx.read_bytes(), teste=True)
            with abrir() as smtp:
                smtp.send_message(msg)
        log.info(f"Envio de TESTE de {competencia} feito para EMAIL_TESTE. Nada arquivado nem registrado.")
        return "teste"

    arquivo = cfg.arquivo
    arquivo.sincronizar()
    envios = arquivo.envios()

    orfaos = sorted(c for c, e in envios.items() if e.get("status") == "enviando")
    if orfaos:
        notificar(
            "CAGED: envio de boletim ÓRFÃO",
            f"Competência(s) {', '.join(orfaos)} ficaram em 'enviando': o processo parou no meio e "
            "não se sabe quem recebeu. NÃO será reenviado automaticamente. Confira o envios.json "
            "no repositório do arquivo e resolva à mão (README, 'Resolver um envio órfão').",
            prioridade="high",
        )
    if competencia in orfaos:
        log.error(f"{competencia} está órfã (enviando); sem reenvio automático.")
        return "orfao"
    if envios.get(competencia, {}).get("status") == "enviado":
        log.info(f"{competencia} já foi enviada em {envios[competencia].get('enviado_em')}; nada a fazer.")
        return "ja_enviado"

    destinatarios = ler_destinatarios(cfg.destinatarios_arquivo)

    arquivados = arquivo.arquivos_da(competencia)
    if arquivados:
        # Sobrou de um run que morreu entre arquivar e gravar `enviando`. Manda o
        # que já está arquivado: regenerar poderia dar números diferentes.
        log.info(f"{competencia} já estava arquivada; reaproveitando os mesmos arquivos.")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            pdf, xlsx = boletim.gerar(cfg.warehouse, competencia, Path(tmp))
            arquivados = arquivo.arquivar(competencia, pdf, xlsx)
    pdf, xlsx = arquivados
    corpo_pdf, corpo_xlsx = pdf.read_bytes(), xlsx.read_bytes()

    arquivo.gravar_estado(
        competencia,
        status="enviando",
        iniciado_em=agora(),
        enviado_em=None,
        sha256_boletim=sha256(pdf),
        sha256_planilha=sha256(xlsx),
        destinatarios_total=len(destinatarios),
        destinatarios_enviados=0,
    )

    enviados, recusados = 0, 0
    try:
        with abrir() as smtp:
            for destinatario in destinatarios:
                msg = montar_mensagem(cfg, destinatario, competencia, corpo_pdf, corpo_xlsx)
                try:
                    smtp.send_message(msg)
                except smtplib.SMTPRecipientsRefused:
                    # Endereço rejeitado pelo servidor: problema daquele
                    # destinatário, não do envio. Segue, mas conta e avisa.
                    recusados += 1
                    continue
                enviados += 1
    except Exception as e:  # noqa: BLE001 — qualquer queda vira órfão explícito
        erro = f"{type(e).__name__}: {e}"[:300]
        try:
            arquivo.gravar_estado(competencia, destinatarios_enviados=enviados, erro=erro)
        except Exception as e2:  # noqa: BLE001
            log.error(f"Não consegui gravar o erro no envios.json: {e2}")
        notificar(
            "CAGED: envio de boletim INTERROMPIDO",
            f"{competencia}: parou após {enviados} de {len(destinatarios)} destinatários ({erro}). "
            "Não será reenviado sozinho: resolva à mão (README, 'Resolver um envio órfão').",
            prioridade="urgent",
        )
        raise EnvioInterrompido(f"{competencia}: {enviados}/{len(destinatarios)} enviados. {erro}") from e

    campos = {"status": "enviado", "enviado_em": agora(), "destinatarios_enviados": enviados,
              "destinatarios_recusados": recusados, "erro": None}
    arquivo.gravar_estado(competencia, **campos)
    if recusados:
        notificar(
            "CAGED: destinatários recusados",
            f"{competencia}: {recusados} endereço(s) foram recusados pelo servidor de e-mail. "
            "Revise a lista de destinatários.",
        )
    log.info(f"{competencia} enviada a {enviados} destinatário(s), {recusados} recusado(s).")
    return "enviado"


def expandir_competencias(args: list[str]) -> list[str]:
    """['202001..202003', '202607'] -> ['202001', '202002', '202003', '202607'], sem repetir."""
    def valida(c: str) -> str:
        if not (re.fullmatch(r"\d{6}", c) and 1 <= int(c[4:]) <= 12):
            raise ValueError(f"Competência inválida: {c!r} (use AAAAMM, ex.: 202607)")
        return c

    saida: list[str] = []
    for a in args:
        if ".." in a:
            ini, fim = (valida(x) for x in a.split("..", 1))
            c = ini
            while c <= fim:
                saida.append(c)
                c = boletim.competencia_deslocada(c, 1)
        else:
            saida.append(valida(a))
    return list(dict.fromkeys(saida))


def arquivar_competencias(competencias: list[str], *, cfg: Config | None = None) -> dict[str, str]:
    """Gera e ARQUIVA o boletim e a planilha de cada competência, sem enviar e-mail e sem
    mexer no envios.json. Serve para constituir o histórico do arquivo.

    Desfecho por competência: 'arquivada' | 'ja_arquivada' | 'sem_dados'.
    - Não sobrescreve nada: o que já está arquivado (enviado ou não) fica como está, porque
      o arquivo guarda o que foi gerado e os sha256 do envios.json descrevem esses bytes.
    - Sai UM commit para o lote inteiro (um deploy do Netlify, não um por competência).
    - O que foi gerado agora reflete o mart de hoje, não "o que foi enviado": no índice
      aparece como "arquivado", não como "enviado em ...".
    """
    log = _logger()
    cfg = cfg or Config.do_ambiente()
    if cfg.arquivo is None:
        raise ConfigIncompleta("Variáveis de ambiente ausentes: ARQUIVO_REPO_URL")
    arquivo = cfg.arquivo
    arquivo.sincronizar()
    envios = arquivo.envios()

    resultado: dict[str, str] = {}
    itens = []
    with tempfile.TemporaryDirectory() as tmp:
        for c in competencias:
            if c in envios or arquivo.arquivos_da(c):
                resultado[c] = "ja_arquivada"
                continue
            try:
                pdf, xlsx = boletim.gerar(cfg.warehouse, c, Path(tmp) / c)
            except ValueError:
                resultado[c] = "sem_dados"
                continue
            itens.append((c, pdf, xlsx))
            resultado[c] = "arquivada"
        if itens:
            novas = ", ".join(c for c, _, _ in itens)
            arquivo.arquivar_lote(itens, f"arquivo: {len(itens)} competência(s) arquivada(s) sem envio ({novas})")
    log.info(f"Arquivamento sem envio: {resultado}")
    return resultado


@task(log_prints=True)
def entregar_boletim_pendente() -> str:
    """Chamada ao fim do flow diário: entrega a competência mais recente do
    mart, se ainda não foi enviada. Sem nada novo, é um no-op silencioso
    (estado normal: nenhum e-mail, nenhum alerta)."""
    cfg = Config.do_ambiente()
    competencia = ultima_competencia(cfg.warehouse)
    if competencia is None:
        _logger().warning("Mart vazio ou inexistente: nada a entregar.")
        return "sem_mart"
    return entregar(competencia, cfg=cfg)


def entrega_habilitada() -> bool:
    return os.environ.get("ENTREGA_HABILITADA", "").strip().lower() in ("1", "true", "sim", "yes")


if __name__ == "__main__":
    args = sys.argv[1:]
    comando = args[0] if args else ""
    if comando == "teste":
        alvo = args[1] if len(args) > 1 else ultima_competencia(WAREHOUSE_PATH)
        print(entregar(alvo, teste=True))
    elif comando == "enviar" and len(args) == 2:
        print(entregar(args[1]))
    elif comando == "arquivar" and len(args) >= 2:
        res = arquivar_competencias(expandir_competencias(args[1:]))
        for desfecho in ("arquivada", "ja_arquivada", "sem_dados"):
            cs = [c for c, d in res.items() if d == desfecho]
            if cs:
                print(f"{desfecho}: {len(cs)} ({cs[0]}..{cs[-1]})" if len(cs) > 3 else f"{desfecho}: {cs}")
    else:
        print(__doc__.split("Uso manual:")[1].rstrip())
        sys.exit(1)
