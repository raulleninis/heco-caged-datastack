"""
Flows de ingestão do Novo CAGED (PDET / Ministério do Trabalho).

Dois flows neste arquivo:
- ingest_caged: roda no cron diário, varre últimos 6 meses procurando lacunas.
  Se encontrar competências não ingeridas, baixa e transforma todas.
  Agendamento via deployment declarado em prefect.yaml, aplicado por
  'prefect deploy' e consumido por 'prefect worker start' (ver start.sh).
- backfill_caged: roda sob demanda (CLI: `python flows/ingest_caged.py
  backfill <ano>`), busca todas as competências de um ano até a mais
  recente já publicada. Transforma uma vez no final.

Observabilidade (F11): falha de qualquer flow dispara alerta (alertas.py);
o flow diário ainda verifica defasagem (falha se a competência mais recente
no warehouse estiver velha demais), registra métricas do run como artifact
do Prefect e dá o ping de heartbeat externo ao terminar bem.

Entrega (F15): com ENTREGA_HABILITADA=true, o flow diário também envia por
e-mail o boletim da competência mais recente e o arquiva (entrega.py). O
backfill nunca envia e-mail.
"""

import re
import statistics
import time
from ftplib import FTP
from pathlib import Path
from datetime import date, datetime, timedelta, timezone

import duckdb
import py7zr
from prefect import flow, task, get_run_logger
from prefect.artifacts import create_markdown_artifact

from alertas import alerta_falha, notificar, ping_heartbeat
from entrega import entrega_habilitada, entregar_boletim_pendente

FTP_HOST = "ftp.mtps.gov.br"
RAW_DIR = Path("/data/raw")
DBT_PROJECT_DIR = Path("/dbt")
WAREHOUSE_PATH = Path("/data/warehouse/caged.duckdb")

# O PDET publica ~28-31 dias após o fechamento da competência (ver F06).
# 60 dias sem a competência seguinte = ~1 mês de folga sobre o normal: ou o
# PDET parou de publicar, ou a ingestão parou de funcionar. Nos dois casos
# alguém precisa olhar.
LIMITE_DEFASAGEM_DIAS = 60

# F12: o PDET publica três arquivos por competência (declaração). MOV: dentro do prazo (a
# competência do arquivo É a de movimentação); FOR: fora do prazo (soma) e EXC: exclusões
# (subtrai), estes dois com movimentações de várias competências anteriores. Ver F12.
TIPOS = ("MOV", "FOR", "EXC")
STAGING = {
    "MOV": "stg_caged_movimentacoes",
    "FOR": "stg_caged_fora_do_prazo",
    "EXC": "stg_caged_exclusoes",
}
# Coluna que identifica o arquivo dentro de cada staging (a de FOR/EXC não é a competência
# de movimentação: um arquivo retroage meses).
COLUNA_ARQUIVO = {"MOV": "competencia_mov", "FOR": "competencia_arquivo", "EXC": "competencia_arquivo"}

# Competência com menos que esta fração da mediana das demais é suspeita
# (fonte truncada, filtro quebrado). Só avalia com >= 3 competências de
# comparação.
FRACAO_MINIMA_LINHAS = 0.5


class DefasagemExcedida(RuntimeError):
    """Competência mais recente no warehouse está velha demais (F11)."""


def competencia_alvo() -> str:
    """Competência (AAAAMM) que devemos buscar hoje: sempre o mês anterior ao atual."""
    hoje = date.today()
    ano, mes = hoje.year, hoje.month - 1
    if mes == 0:
        mes, ano = 12, ano - 1
    return f"{ano}{mes:02d}"


def meses_candidatos(meses_para_tras: int = 6) -> list[str]:
    """Últimos N meses (AAAAMM) contados a partir do mês atual, do mais antigo ao mais recente."""
    hoje = date.today()
    candidatos = []
    for i in range(meses_para_tras):
        ano, mes = hoje.year, hoje.month - i
        if mes <= 0:
            mes += 12
            ano -= 1
        candidatos.append(f"{ano}{mes:02d}")
    return sorted(candidatos)


def fim_da_competencia(competencia: str) -> date:
    """Último dia do mês da competência (AAAAMM)."""
    ano, mes = int(competencia[:4]), int(competencia[4:])
    primeiro_do_proximo = date(ano + (mes == 12), mes % 12 + 1, 1)
    return primeiro_do_proximo - timedelta(days=1)


def _linhas_por_competencia() -> dict[str, int]:
    """Linhas da staging por competência (AAAAMM). Vazio se o warehouse ou a
    tabela ainda não existem (primeira execução)."""
    if not WAREHOUSE_PATH.exists():
        return {}
    con = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
    try:
        # Só tabela física conta. Versões antigas do projeto criaram a staging
        # como VIEW sobre os .txt (F09 mudou para incremental): consultá-la
        # varreria todos os .txt brutos (GBs) e estouraria memória, e uma view
        # não guarda dado nenhum — não prova que nada foi ingerido.
        tipo = con.execute(
            "select table_type from information_schema.tables "
            "where table_name = 'stg_caged_movimentacoes'"
        ).fetchone()
        if not tipo or tipo[0] != "BASE TABLE":
            return {}
        rows = con.execute(
            "select competencia_mov, count(*) from stg_caged_movimentacoes group by 1"
        ).fetchall()
    finally:
        con.close()
    return {str(c): n for c, n in rows}


def _arquivos_ingeridos() -> dict[str, set[str]]:
    """tipo -> competências (AAAAMM) dos arquivos já carregados no warehouse.

    FOR e EXC vêm só do registro `ingestao_arquivos`: um arquivo pode ter ZERO linhas do
    município e nem por isso deixou de ser ingerido (senão seria rebaixado todo dia). O MOV
    também soma as competências da staging, que é o que valia antes do registro existir.
    """
    saida: dict[str, set[str]] = {t: set() for t in TIPOS}
    if WAREHOUSE_PATH.exists():
        con = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
        try:
            existe = con.execute(
                "select 1 from information_schema.tables "
                "where table_name = 'ingestao_arquivos' and table_type = 'BASE TABLE'"
            ).fetchone()
            if existe:
                for tipo, comp in con.execute("select tipo, competencia_arquivo from ingestao_arquivos").fetchall():
                    saida[tipo].add(str(comp))
        finally:
            con.close()
    saida["MOV"] |= set(_linhas_por_competencia())
    return saida


def _registrar_ingestao(tipo: str, competencia: str) -> None:
    """Marca o arquivo (tipo, competência) como carregado, com a contagem de linhas do
    município. Roda depois do `dbt run` da staging; reprocessar substitui o registro."""
    con = duckdb.connect(str(WAREHOUSE_PATH))
    try:
        con.execute(
            "create table if not exists ingestao_arquivos "
            "(tipo varchar, competencia_arquivo bigint, linhas bigint, ingerido_em timestamp)"
        )
        linhas = con.execute(
            f"select count(*) from {STAGING[tipo]} where {COLUNA_ARQUIVO[tipo]} = ?", [int(competencia)]
        ).fetchone()[0]
        con.execute("delete from ingestao_arquivos where tipo = ? and competencia_arquivo = ?", [tipo, int(competencia)])
        con.execute(
            "insert into ingestao_arquivos values (?, ?, ?, ?)",
            [tipo, int(competencia), linhas, datetime.now(timezone.utc).replace(tzinfo=None)],
        )
    finally:
        con.close()


def _linhas_por_arquivo() -> dict[tuple[str, str], int]:
    """(tipo, competência) -> linhas do município, a partir do registro de ingestão."""
    if not WAREHOUSE_PATH.exists():
        return {}
    con = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
    try:
        if not con.execute(
            "select 1 from information_schema.tables where table_name = 'ingestao_arquivos'"
        ).fetchone():
            return {}
        return {(t, str(c)): n for t, c, n in con.execute(
            "select tipo, competencia_arquivo, linhas from ingestao_arquivos"
        ).fetchall()}
    finally:
        con.close()


def _pendentes(
    publicados: dict[str, list[str]], ingeridos: dict[str, set[str]], tipos: tuple[str, ...] = TIPOS
) -> list[tuple[str, str]]:
    """(tipo, competência) publicados no FTP e ainda não carregados, da competência mais
    antiga para a mais recente e, dentro dela, na ordem MOV, FOR, EXC."""
    return [
        (t, c)
        for c in sorted(publicados)
        for t in TIPOS
        if t in tipos and t in publicados[c] and c not in ingeridos[t]
    ]


@task(log_prints=True)
def arquivos_ja_ingeridos() -> dict[str, set[str]]:
    logger = get_run_logger()
    ingeridos = _arquivos_ingeridos()
    logger.info({t: len(v) for t, v in ingeridos.items()} | {"MOV recentes": sorted(ingeridos["MOV"])[-6:]})
    return ingeridos


def competencias_do_ano(ano: int) -> list[str]:
    """Todas as competências de 'ano', de janeiro até a competência-alvo (inclusive)."""
    alvo = competencia_alvo()
    competencias = []
    for mes in range(1, 13):
        comp = f"{ano}{mes:02d}"
        if comp > alvo:
            break
        competencias.append(comp)
    return competencias


@task(log_prints=True)
def arquivos_no_ftp(competencia: str) -> list[str]:
    """Tipos (MOV/FOR/EXC) publicados no FTP para a competência. Lista vazia = pasta ainda
    não existe ou sem arquivos (estado normal nas semanas antes da publicação)."""
    logger = get_run_logger()
    ano = competencia[:4]
    caminho = f"/pdet/microdados/NOVO CAGED/{ano}/{competencia}"

    ftp = FTP(FTP_HOST, timeout=30)
    ftp.login()
    try:
        ftp.cwd(caminho)
        arquivos = ftp.nlst()
    except Exception as e:
        logger.info(f"Pasta '{caminho}' ainda não existe ({e}). Competência {competencia} não publicada.")
        return []
    finally:
        ftp.quit()

    publicados = [t for t in TIPOS if f"CAGED{t}{competencia}.7z" in arquivos]
    logger.info(f"{competencia}: publicados no FTP = {publicados or 'nenhum'}")
    return publicados


@task(retries=3, retry_delay_seconds=60, log_prints=True)
def baixar_arquivo(competencia: str, tipo: str = "MOV") -> Path:
    logger = get_run_logger()
    ano = competencia[:4]
    caminho = f"/pdet/microdados/NOVO CAGED/{ano}/{competencia}"
    nome_arquivo = f"CAGED{tipo}{competencia}.7z"
    destino = RAW_DIR / nome_arquivo
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    ftp = FTP(FTP_HOST, timeout=60)
    ftp.login()
    ftp.cwd(caminho)
    with open(destino, "wb") as f:
        ftp.retrbinary(f"RETR {nome_arquivo}", f.write)
    ftp.quit()

    logger.info(f"Baixado: {destino} ({destino.stat().st_size / 1_048_576:.1f} MB)")
    return destino


@task(log_prints=True)
def extrair_7z(caminho_arquivo: Path) -> Path:
    logger = get_run_logger()
    destino = RAW_DIR / "extraido"
    destino.mkdir(exist_ok=True)

    with py7zr.SevenZipFile(caminho_arquivo, mode="r") as archive:
        archive.extractall(path=destino)

    logger.info(f"Extraído em: {destino}")
    return destino


@task(log_prints=True)
def deletar_arquivo_7z(caminho_arquivo: Path) -> None:
    logger = get_run_logger()
    try:
        caminho_arquivo.unlink()
        logger.info(f"Arquivo .7z deletado: {caminho_arquivo}")
    except FileNotFoundError:
        logger.warning(f"Arquivo .7z não encontrado (pode já ter sido deletado): {caminho_arquivo}")
    except Exception as e:
        logger.error(f"Erro ao deletar .7z: {e}")
        raise


@task(log_prints=True)
def deletar_txt_extraido(competencia: str, tipo: str = "MOV") -> None:
    """Apaga o .txt extraído de um arquivo (MOV: ~450MB, Brasil inteiro; FOR/EXC: poucos MB).

    Só deve ser chamada depois de staging + testes terem passado: a partir daí o dado do
    município já está no warehouse e o FTP público continua sendo a fonte de verdade caso
    seja preciso reprocessar (política D06).
    """
    logger = get_run_logger()
    caminho = RAW_DIR / "extraido" / f"CAGED{tipo}{competencia}.txt"
    try:
        tamanho_mb = caminho.stat().st_size / 1_048_576
        caminho.unlink()
        logger.info(f"Arquivo .txt deletado: {caminho} ({tamanho_mb:.1f} MB liberados)")
    except FileNotFoundError:
        logger.warning(f"Arquivo .txt não encontrado (pode já ter sido deletado): {caminho}")


@task(log_prints=True)
def run_dbt(comando: list[str], dbt_vars: dict | None = None) -> str:
    import json
    import subprocess
    logger = get_run_logger()
    cmd = ["dbt", *comando, "--project-dir", str(DBT_PROJECT_DIR), "--profiles-dir", str(DBT_PROJECT_DIR)]
    if dbt_vars:
        cmd += ["--vars", json.dumps(dbt_vars)]
    logger.info(f"Executando: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    logger.info(result.stdout)
    if result.returncode != 0:
        logger.error(f"stdout:\n{result.stdout}")
        logger.error(f"stderr:\n{result.stderr}")
        raise RuntimeError(f"dbt {' '.join(comando)} falhou")
    return result.stdout


def _testes_em_warn(saida_dbt: str) -> list[str]:
    """Linhas de resultado dbt com status WARN (testes de plausibilidade que
    reprovaram com severity=warn — D04). Devolve [] se nenhum."""
    limpo = re.sub(r"\x1b\[[0-9;]*m", "", saida_dbt)
    return [
        re.sub(r"^\d\d:\d\d:\d\d\s+", "", linha).strip()
        for linha in limpo.splitlines()
        if re.search(r"\bWARN\b", linha) and "START" not in linha and "Done." not in linha
    ]


def _competencias_com_volume_suspeito(
    linhas: dict[str, int], processadas: list[str]
) -> list[str]:
    """Competências processadas neste run com menos linhas que
    FRACAO_MINIMA_LINHAS x a mediana das demais no warehouse."""
    suspeitas = []
    for competencia in processadas:
        outras = [n for c, n in linhas.items() if c != competencia]
        if len(outras) < 3 or competencia not in linhas:
            continue
        mediana = statistics.median(outras)
        if linhas[competencia] < FRACAO_MINIMA_LINHAS * mediana:
            suspeitas.append(
                f"{competencia}: {linhas[competencia]} linhas vs mediana {mediana:.0f} das demais"
            )
    return suspeitas


def _baixar_e_extrair(competencia: str, tipo: str = "MOV") -> dict:
    """Baixa, extrai e apaga o .7z. Devolve métricas do download."""
    inicio = time.monotonic()
    arquivo = baixar_arquivo(competencia, tipo)
    mb = arquivo.stat().st_size / 1_048_576
    extrair_7z(arquivo)
    deletar_arquivo_7z(arquivo)
    return {
        "tipo": tipo,
        "competencia": competencia,
        "mb_baixados": round(mb, 1),
        "segundos": round(time.monotonic() - inicio),
    }


def _transformar(baixados: list[tuple[str, str]]) -> None:
    """Roda a staging de cada arquivo baixado, incrementalmente (um arquivo por vez, ~500MB de
    pico para o MOV, não ~3GB de uma vez — ver comentário em stg_caged_movimentacoes.sql) e
    depois materializa os marts (pequenos, processam tudo de uma vez sem risco de memória) e
    os testes. Só depois que os testes passam os .txt são deletados (F07 fase 2): se algo
    falhar, os arquivos ficam em disco para diagnóstico.

    `baixados` é uma lista de (tipo, competência). Cada arquivo carregado entra no registro
    de ingestão logo depois da sua staging."""
    logger = get_run_logger()
    for tipo, competencia in baixados:
        logger.info(f"Transformando staging {tipo} de {competencia}...")
        run_dbt(
            ["run", "--select", STAGING[tipo]],
            dbt_vars={"competencia_arquivo": competencia},
        )
        _registrar_ingestao(tipo, competencia)

    logger.info("Materializando marts...")
    run_dbt(["run", "--select", "path:models/marts"])
    saida_testes = run_dbt(["test"])

    avisos = _testes_em_warn(saida_testes)
    if avisos:
        logger.warning(f"{len(avisos)} teste(s) dbt em WARN: {avisos}")
        notificar(
            "CAGED: testes de plausibilidade em WARN",
            "O dado foi carregado, mas está suspeito:\n" + "\n".join(avisos),
        )

    # Além dos deste run: .txt órfãos de arquivos que já estão no warehouse (sobras de um
    # run anterior que falhou nos testes — os testes acabaram de passar, então o dado está
    # validado).
    ingeridos = _arquivos_ingeridos()
    presentes = set()
    for p in (RAW_DIR / "extraido").glob("CAGED*.txt"):
        m = re.fullmatch(r"CAGED(MOV|FOR|EXC)(\d{6})\.txt", p.name)
        if m:
            presentes.add((m.group(1), m.group(2)))
    orfaos = {(t, c) for t, c in presentes if c in ingeridos[t]}
    for tipo, competencia in sorted(set(baixados) | orfaos, key=lambda x: (x[1], TIPOS.index(x[0]))):
        deletar_txt_extraido(competencia, tipo)


@task(log_prints=True)
def verificar_defasagem(hoje: date | None = None) -> None:
    """Falha se a competência mais recente no warehouse fechou há mais de
    LIMITE_DEFASAGEM_DIAS. É o alerta de SILÊNCIO: distingue "PDET ainda não
    publicou" (normal, ~30 dias) de "está quebrado há meses" — que antes
    produziam o mesmo sinal, um run verde."""
    logger = get_run_logger()
    hoje = hoje or date.today()
    ingeridas = set(_linhas_por_competencia())
    if not ingeridas:
        raise DefasagemExcedida("Nenhuma competência no warehouse: nada foi ingerido ainda.")

    ultima = max(ingeridas)
    idade = (hoje - fim_da_competencia(ultima)).days
    if idade > LIMITE_DEFASAGEM_DIAS:
        raise DefasagemExcedida(
            f"Competência mais recente no warehouse: {ultima}, fechada há {idade} dias "
            f"(limite {LIMITE_DEFASAGEM_DIAS}). O PDET não publicou a seguinte ou a "
            "ingestão parou de funcionar."
        )
    logger.info(f"Defasagem ok: última competência {ultima}, fechada há {idade} dias.")


@task(log_prints=True)
def registrar_metricas(metricas: list[dict], inicio: float) -> None:
    """Artifact do Prefect com métricas do run + alerta de volume suspeito.
    Com metricas vazio, registra que nada novo foi publicado (estado normal,
    verde, mas registrado)."""
    logger = get_run_logger()
    duracao = round(time.monotonic() - inicio)
    linhas = _linhas_por_competencia()
    por_arquivo = _linhas_por_arquivo()
    ultima = max(linhas) if linhas else "—"

    if not metricas:
        md = (
            f"Nenhuma competência nova publicada no PDET (estado normal).\n\n"
            f"- Última no warehouse: **{ultima}**\n- Duração: {duracao}s\n"
        )
    else:
        md = "| competência | arquivo | MB baixados | linhas (município) | download+extração (s) |\n|---|---|---|---|---|\n"
        for m in metricas:
            n = linhas.get(m["competencia"], 0) if m["tipo"] == "MOV" else por_arquivo.get((m["tipo"], m["competencia"]), 0)
            md += f"| {m['competencia']} | {m['tipo']} | {m['mb_baixados']} | {n} | {m['segundos']} |\n"
        md += f"\nDuração total do run: {duracao}s. Última no warehouse: **{ultima}**.\n"
    logger.info(md)
    create_markdown_artifact(key="metricas-ingestao", markdown=md, description="Métricas do último run")

    # Volume suspeito só faz sentido para o MOV (FOR/EXC variam muito de mês a mês).
    suspeitas = _competencias_com_volume_suspeito(
        linhas, [m["competencia"] for m in metricas if m["tipo"] == "MOV"]
    )
    if suspeitas:
        logger.warning(f"Volume suspeito: {suspeitas}")
        notificar(
            "CAGED: volume de linhas suspeito",
            "Competência com muito menos linhas que as anteriores:\n" + "\n".join(suspeitas),
        )


@flow(name="ingest-caged", log_prints=True, on_failure=[alerta_falha], on_crashed=[alerta_falha])
def ingest_caged():
    logger = get_run_logger()
    inicio = time.monotonic()
    candidatos = meses_candidatos(meses_para_tras=6)
    ingeridos = arquivos_ja_ingeridos()

    # FOR e EXC de uma competência podem aparecer depois do MOV: por isso o FTP é consultado
    # para todos os candidatos, e a decisão é por arquivo (tipo, competência).
    publicados = {c: arquivos_no_ftp(c) for c in candidatos}
    pendentes = _pendentes(publicados, ingeridos)

    metricas = []
    if pendentes:
        logger.info(f"Arquivos pendentes (últimos 6 meses): {pendentes}")
        for tipo, competencia in pendentes:
            logger.info(f"Processando {tipo} de {competencia}...")
            metricas.append(_baixar_e_extrair(competencia, tipo))
        logger.info(f"Ingestão concluída. Arquivos baixados: {pendentes}")
        _transformar(pendentes)
    else:
        logger.info("Nenhum arquivo novo publicado nos últimos 6 meses (estado normal).")

    registrar_metricas(metricas, inicio)
    verificar_defasagem()
    # F15: e-mail + arquivo. Desligado por padrão (ENTREGA_HABILITADA). Vem
    # depois da defasagem e antes do heartbeat: uma entrega que falha deixa o
    # run vermelho e o heartbeat em /fail, em vez de passar por verde.
    if entrega_habilitada():
        entregar_boletim_pendente()
    ping_heartbeat()


@flow(name="backfill-caged", log_prints=True, on_failure=[alerta_falha], on_crashed=[alerta_falha])
def backfill_caged(ano: int = 2026, tipos: tuple[str, ...] = TIPOS, refazer: bool = False):
    """Baixa e transforma os arquivos de um ano, de janeiro até a competência mais recente
    já publicada. Por padrão pula o que já está carregado (`refazer=True` reprocessa)."""
    logger = get_run_logger()
    inicio = time.monotonic()
    competencias = competencias_do_ano(ano)
    logger.info(f"Competências candidatas para {ano}: {competencias} | tipos: {tipos}")

    ingeridos = {t: set() for t in TIPOS} if refazer else arquivos_ja_ingeridos()
    publicados = {c: arquivos_no_ftp(c) for c in competencias}
    pendentes = _pendentes(publicados, ingeridos, tuple(tipos))

    metricas = [_baixar_e_extrair(c, t) for t, c in pendentes]
    logger.info(f"Backfill concluído. Arquivos baixados: {pendentes}")

    if pendentes:
        logger.info(f"Transformando {len(pendentes)} arquivo(s) com dbt...")
        _transformar(pendentes)
    else:
        logger.info("Nada a baixar (tudo já carregado ou ainda não publicado), pulando dbt.")
    registrar_metricas(metricas, inicio)


def _anos_do_argumento(arg: str) -> list[int]:
    """'2026' -> [2026]; '2020..2026' -> [2020, ..., 2026]."""
    if ".." in arg:
        ini, fim = (int(x) for x in arg.split("..", 1))
        return list(range(ini, fim + 1))
    return [int(arg)]


if __name__ == "__main__":
    import sys

    USO = (
        "Uso: python flows/ingest_caged.py backfill <ano | ano..ano> [--tipos MOV,FOR,EXC] [--refazer]\n"
        "  ex.: backfill 2020..2026 --tipos FOR,EXC   (só os arquivos pequenos, do histórico todo)\n"
        "O agendamento diário roda via 'prefect deploy' + worker (ver start.sh), não mais via .serve() direto."
    )
    args = sys.argv[1:]
    if not args or args[0] != "backfill" or len(args) < 2:
        print(USO)
        sys.exit(1)

    tipos = TIPOS
    if "--tipos" in args:
        tipos = tuple(t.strip().upper() for t in args[args.index("--tipos") + 1].split(","))
        if not set(tipos) <= set(TIPOS):
            print(f"Tipos inválidos: {tipos}. Use MOV, FOR e/ou EXC.")
            sys.exit(1)
    for ano in _anos_do_argumento(args[1]):
        backfill_caged(ano, tipos=tipos, refazer="--refazer" in args)
