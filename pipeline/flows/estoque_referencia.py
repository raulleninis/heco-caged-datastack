"""
Estoque de referência do MTE (F20): a âncora do estoque de emprego.

O painel do Novo CAGED não acumula movimentações desde 2020. Ele parte do "Estoque de
Referência" que o MTE publica no gov.br (não no FTP), um arquivo por ano com o estoque por
município × subclasse CNAE ao fim de dezembro do ano anterior (o de 2026 é o de 202512), e
soma ou subtrai os saldos a partir dele. Quando o MTE troca esse arquivo, a série inteira do
painel se desloca, até jan/2020. Foi o que tirou o marco zero manual de mar/2020 do lugar
(F20; o marco zero está desativado, F16).

O que este módulo faz, a cada run do flow diário, antes da ingestão:
- baixa o zip do ano em uso (`ANO_REFERENCIA`, ~2,3 MB) e compara o SHA-256 do .txt com o do
  último carregado. Igual: nada a fazer. Diferente (ou primeira vez): grava as linhas de Sergipe
  em `estoque_referencia` e um registro em `estoque_referencia_arquivos`; o flow recalcula os
  marts mesmo sem competência nova.
- olha a página da pasta: se aparecer um ano mais novo que `ANO_REFERENCIA`, avisa UMA vez
  (`estoque_referencia_avisos`). Trocar o ano é decisão manual: muda a âncora da série.

Falha de rede ou formato inesperado nunca derruba o flow: fica no log, vira alerta, e o estoque
segue com a referência já carregada. Sem nenhuma carregada, o mart_estoque fica com estoque NULL
(D11: a falta de âncora não bloqueia o fluxo).

Manual:  python flows/estoque_referencia.py verificar
"""

import hashlib
import io
import re
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from alertas import _logger, notificar

# Ano do arquivo em uso. Trocar = reancorar a série inteira: só depois de conferir com o painel.
ANO_REFERENCIA = 2026
UF = "28"
WAREHOUSE_PATH = Path("/data/warehouse/caged.duckdb")

URL_PASTA = (
    "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/acoes-e-programas/"
    "programas-projetos-acoes-obras-e-atividades/estatisticas-trabalho/estoque-de-referencia"
)
# O gov.br responde 403 a HEAD e a clientes sem cara de navegador; GET com User-Agent funciona.
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
CABECALHO = "codmun;cnae20subclas;estoqueref"


class FormatoInesperado(ValueError):
    """O zip ou o .txt não têm a forma conhecida (um .txt, cabeçalho CABECALHO)."""


@dataclass
class Arquivo:
    ano: int
    nome: str              # nome do .txt dentro do zip
    sha256: str            # do .txt: decide se mudou (o zip pode ser refeito com o mesmo conteúdo)
    sha256_zip: str
    bytes_zip: int
    linhas: list[tuple[str, str, int]]   # (codmun, subclasse, estoque), só da UF


def url_arquivo(ano: int) -> str:
    return f"{URL_PASTA}/estoque-de-referencia-{ano}.zip/@@download/file"


def competencia_referencia(ano: int) -> int:
    """O arquivo de um ano é o estoque ao fim de dezembro do ano anterior."""
    return (ano - 1) * 100 + 12


def baixar(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def ler_zip(conteudo: bytes, ano: int, uf: str = UF) -> Arquivo:
    try:
        z = zipfile.ZipFile(io.BytesIO(conteudo))
    except zipfile.BadZipFile as e:
        raise FormatoInesperado(f"não é um zip ({e})") from e
    txts = [n for n in z.namelist() if n.lower().endswith(".txt")]
    if len(txts) != 1:
        raise FormatoInesperado(f"esperado um .txt no zip, achei {z.namelist()}")
    bruto = z.read(txts[0])
    texto = bruto.decode("latin-1").splitlines()
    if not texto or texto[0].strip().lower() != CABECALHO:
        raise FormatoInesperado(f"cabeçalho inesperado: {texto[0] if texto else '(vazio)'!r}")
    linhas = []
    for i, linha in enumerate(texto[1:], start=2):
        if not linha.strip():
            continue
        partes = linha.split(";")
        if len(partes) != 3:
            raise FormatoInesperado(f"linha {i} com {len(partes)} campos: {linha!r}")
        codmun, subclasse, estoque = (p.strip() for p in partes)
        if codmun.startswith(uf):
            linhas.append((codmun, subclasse, int(estoque)))
    if not linhas:
        raise FormatoInesperado(f"nenhuma linha da UF {uf}")
    return Arquivo(
        ano=ano,
        nome=txts[0],
        sha256=hashlib.sha256(bruto).hexdigest(),
        sha256_zip=hashlib.sha256(conteudo).hexdigest(),
        bytes_zip=len(conteudo),
        linhas=linhas,
    )


def anos_publicados(html: str) -> set[int]:
    """Anos com arquivo listado na página da pasta (estoque-de-referencia-AAAA.zip)."""
    return {int(a) for a in re.findall(r"estoque-de-referencia-(\d{4})\.zip", html)}


def garantir_tabelas(con) -> None:
    """Cria as tabelas vazias: o dbt lê `estoque_referencia` como source e falharia sem ela."""
    con.execute(
        "create table if not exists estoque_referencia "
        "(ano_referencia integer, competencia_referencia bigint, codmun varchar, subclasse varchar, estoque bigint)"
    )
    con.execute(
        "create table if not exists estoque_referencia_arquivos "
        "(ano_referencia integer, competencia_referencia bigint, arquivo varchar, sha256 varchar, "
        "sha256_zip varchar, bytes_zip bigint, linhas_uf bigint, estoque_uf bigint, carregado_em timestamp)"
    )
    con.execute("create table if not exists estoque_referencia_avisos (ano_referencia integer, visto_em timestamp)")


def ultimo_carregado(con, ano: int) -> str | None:
    """SHA-256 do .txt carregado por último para o ano (None se nunca)."""
    r = con.execute(
        "select sha256 from estoque_referencia_arquivos where ano_referencia = ? "
        "order by carregado_em desc limit 1",
        [ano],
    ).fetchone()
    return r[0] if r else None


def carregar(con, arq: Arquivo) -> None:
    """Substitui o conteúdo de `estoque_referencia` pelo do arquivo (um ano por vez: é a âncora
    em uso) e registra a carga. Numa transação: nunca fica meia referência."""
    comp = competencia_referencia(arq.ano)
    agora = datetime.now(timezone.utc).replace(tzinfo=None)
    con.execute("begin")
    try:
        con.execute("delete from estoque_referencia")
        con.executemany(
            "insert into estoque_referencia values (?, ?, ?, ?, ?)",
            [(arq.ano, comp, m, s, e) for m, s, e in arq.linhas],
        )
        con.execute(
            "insert into estoque_referencia_arquivos values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [arq.ano, comp, arq.nome, arq.sha256, arq.sha256_zip, arq.bytes_zip,
             len(arq.linhas), sum(e for _, _, e in arq.linhas), agora],
        )
        con.execute("commit")
    except Exception:
        con.execute("rollback")
        raise


def _avisar_ano_novo(con, html: str, ano: int) -> list[int]:
    """Avisa (uma vez por ano) que o MTE publicou referência mais nova que a em uso."""
    novos = sorted(a for a in anos_publicados(html) if a > ano)
    ja_vistos = {r[0] for r in con.execute("select ano_referencia from estoque_referencia_avisos").fetchall()}
    agora = datetime.now(timezone.utc).replace(tzinfo=None)
    for a in novos:
        if a in ja_vistos:
            continue
        notificar(
            f"CAGED: estoque de referência {a} publicado",
            f"O MTE publicou o estoque de referência {a}; o pipeline segue ancorado no de {ano}. "
            "Trocar ANO_REFERENCIA (flows/estoque_referencia.py) reancora a série inteira: "
            "conferir com o painel antes. Ver docs/fatias/F20.",
        )
        con.execute("insert into estoque_referencia_avisos values (?, ?)", [a, agora])
    return novos


def verificar(warehouse: Path = WAREHOUSE_PATH, ano: int = ANO_REFERENCIA, baixar=baixar) -> str:
    """Confere o arquivo do MTE com o carregado. Devolve:
    'carregado' (primeira carga), 'mudou' (MTE trocou o arquivo; recarregado), 'igual' ou
    'indisponivel' (falha de rede/formato; nada mudou no warehouse). Nos dois primeiros, os
    marts precisam ser recalculados."""
    logger = _logger()
    warehouse.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(warehouse))
    try:
        garantir_tabelas(con)
        anterior = ultimo_carregado(con, ano)
        try:
            arq = ler_zip(baixar(url_arquivo(ano)), ano)
        except Exception as e:
            logger.warning(f"Estoque de referência {ano} indisponível: {e}")
            notificar(
                "CAGED: estoque de referência indisponível",
                f"Não consegui conferir o estoque de referência {ano} no gov.br ({e}). "
                + ("O estoque segue com o arquivo já carregado." if anterior
                   else "Nenhum arquivo carregado ainda: o estoque fica NULL até a próxima tentativa."),
                prioridade="low",
            )
            return "indisponivel"

        if arq.sha256 == anterior:
            logger.info(f"Estoque de referência {ano} sem alteração (sha256 {arq.sha256[:12]}).")
            estado = "igual"
        else:
            carregar(con, arq)
            estado = "carregado" if anterior is None else "mudou"
            logger.info(
                f"Estoque de referência {ano} {estado}: {len(arq.linhas)} linhas da UF {UF}, "
                f"sha256 {arq.sha256[:12]}" + (f" (antes {anterior[:12]})" if anterior else "")
            )
            if estado == "mudou":
                notificar(
                    f"CAGED: estoque de referência {ano} alterado pelo MTE",
                    f"O arquivo mudou (sha256 {anterior[:12]} -> {arq.sha256[:12]}). Recarregado; "
                    "o estoque de toda a série será recalculado neste run.",
                )

        try:
            _avisar_ano_novo(con, baixar(URL_PASTA).decode("utf-8", "ignore"), ano)
        except Exception as e:
            logger.warning(f"Não consegui ler a página do estoque de referência: {e}")
        return estado
    finally:
        con.close()


if __name__ == "__main__":
    import sys

    if sys.argv[1:] != ["verificar"]:
        print("Uso: python flows/estoque_referencia.py verificar")
        sys.exit(1)
    print(verificar())
