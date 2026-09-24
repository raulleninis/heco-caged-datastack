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
"""

import re
import statistics
import time
from ftplib import FTP
from pathlib import Path
from datetime import date, timedelta

import duckdb
import py7zr
from prefect import flow, task, get_run_logger
from prefect.artifacts import create_markdown_artifact

from alertas import alerta_falha, notificar, ping_heartbeat

FTP_HOST = "ftp.mtps.gov.br"
RAW_DIR = Path("/data/raw")
DBT_PROJECT_DIR = Path("/dbt")
WAREHOUSE_PATH = Path("/data/warehouse/caged.duckdb")

# O PDET publica ~28-31 dias após o fechamento da competência (ver F06).
# 60 dias sem a competência seguinte = ~1 mês de folga sobre o normal: ou o
# PDET parou de publicar, ou a ingestão parou de funcionar. Nos dois casos
# alguém precisa olhar.
LIMITE_DEFASAGEM_DIAS = 60

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


@task(log_prints=True)
def competencias_ja_ingeridas() -> set[str]:
    """Competências (AAAAMM) que já estão na staging do warehouse.

    Consulta o .duckdb, não o filesystem: o .txt extraído é deletado depois
    que a competência foi transformada e testada (F07 fase 2), então a
    presença dele em disco não diz mais nada. Warehouse ou tabela
    inexistente (primeira execução) significa "nada ingerido ainda".
    """
    logger = get_run_logger()
    ingeridas = set(_linhas_por_competencia())
    logger.info(f"Competências já ingeridas: {sorted(ingeridas)}")
    return ingeridas


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
def arquivo_existe_no_ftp(competencia: str) -> bool:
    logger = get_run_logger()
    ano = competencia[:4]
    caminho = f"/pdet/microdados/NOVO CAGED/{ano}/{competencia}"
    nome_arquivo = f"CAGEDMOV{competencia}.7z"

    ftp = FTP(FTP_HOST, timeout=30)
    ftp.login()
    try:
        ftp.cwd(caminho)
        arquivos = ftp.nlst()
    except Exception as e:
        logger.info(f"Pasta '{caminho}' ainda não existe ({e}). Competência {competencia} não publicada.")
        return False
    finally:
        ftp.quit()

    existe = nome_arquivo in arquivos
    logger.info(f"{'Encontrado' if existe else 'Ainda não publicado'}: {nome_arquivo}")
    return existe


@task(retries=3, retry_delay_seconds=60, log_prints=True)
def baixar_arquivo(competencia: str) -> Path:
    logger = get_run_logger()
    ano = competencia[:4]
    caminho = f"/pdet/microdados/NOVO CAGED/{ano}/{competencia}"
    nome_arquivo = f"CAGEDMOV{competencia}.7z"
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
def deletar_txt_extraido(competencia: str) -> None:
    """Apaga o .txt extraído (~450MB, Brasil inteiro) de uma competência.

    Só deve ser chamada depois de staging + testes terem passado: a partir
    daí o dado do município já está no warehouse e o FTP público continua
    sendo a fonte de verdade caso seja preciso reprocessar (política D06).
    """
    logger = get_run_logger()
    caminho = RAW_DIR / "extraido" / f"CAGEDMOV{competencia}.txt"
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


def _baixar_e_extrair(competencia: str) -> dict:
    """Baixa, extrai e apaga o .7z. Devolve métricas do download."""
    inicio = time.monotonic()
    arquivo = baixar_arquivo(competencia)
    mb = arquivo.stat().st_size / 1_048_576
    extrair_7z(arquivo)
    deletar_arquivo_7z(arquivo)
    return {
        "competencia": competencia,
        "mb_baixados": round(mb, 1),
        "segundos": round(time.monotonic() - inicio),
    }


def _transformar(baixadas: list[str]) -> None:
    """Roda a staging incrementalmente (uma competência por vez, ~500MB de
    pico por execução, não ~3GB de uma vez — ver comentário em
    stg_caged_movimentacoes.sql) e depois materializa o mart (pequeno,
    processa tudo de uma vez sem risco de memória) e os testes. Só depois
    que os testes passam os .txt são deletados (F07 fase 2): se algo
    falhar, os arquivos ficam em disco para diagnóstico."""
    logger = get_run_logger()
    for competencia in baixadas:
        logger.info(f"Transformando staging para {competencia}...")
        run_dbt(
            ["run", "--select", "stg_caged_movimentacoes"],
            dbt_vars={"competencia_arquivo": competencia},
        )

    logger.info("Materializando mart...")
    run_dbt(["run", "--select", "mart_caged_mensal_grupamento"])
    saida_testes = run_dbt(["test"])

    avisos = _testes_em_warn(saida_testes)
    if avisos:
        logger.warning(f"{len(avisos)} teste(s) dbt em WARN: {avisos}")
        notificar(
            "CAGED: testes de plausibilidade em WARN",
            "O dado foi carregado, mas está suspeito:\n" + "\n".join(avisos),
        )

    for competencia in baixadas:
        deletar_txt_extraido(competencia)


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
    ultima = max(linhas) if linhas else "—"

    if not metricas:
        md = (
            f"Nenhuma competência nova publicada no PDET (estado normal).\n\n"
            f"- Última no warehouse: **{ultima}**\n- Duração: {duracao}s\n"
        )
    else:
        md = "| competência | MB baixados | linhas (município) | download+extração (s) |\n|---|---|---|---|\n"
        for m in metricas:
            md += (
                f"| {m['competencia']} | {m['mb_baixados']} | "
                f"{linhas.get(m['competencia'], 0)} | {m['segundos']} |\n"
            )
        md += f"\nDuração total do run: {duracao}s. Última no warehouse: **{ultima}**.\n"
    logger.info(md)
    create_markdown_artifact(key="metricas-ingestao", markdown=md, description="Métricas do último run")

    suspeitas = _competencias_com_volume_suspeito(linhas, [m["competencia"] for m in metricas])
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
    ingeridas = competencias_ja_ingeridas()

    faltantes = [c for c in candidatos if c not in ingeridas and arquivo_existe_no_ftp(c)]

    metricas = []
    if faltantes:
        logger.info(f"Competências faltantes (últimos 6 meses): {faltantes}")
        for competencia in faltantes:
            logger.info(f"Processando competência {competencia}...")
            metricas.append(_baixar_e_extrair(competencia))
        logger.info(f"Ingestão concluída. Competências baixadas: {faltantes}")
        _transformar(faltantes)
    else:
        logger.info("Nenhuma competência nova publicada nos últimos 6 meses (estado normal).")

    registrar_metricas(metricas, inicio)
    verificar_defasagem()
    ping_heartbeat()


@flow(name="backfill-caged", log_prints=True, on_failure=[alerta_falha], on_crashed=[alerta_falha])
def backfill_caged(ano: int = 2026):
    logger = get_run_logger()
    inicio = time.monotonic()
    competencias = competencias_do_ano(ano)
    logger.info(f"Competências candidatas para {ano}: {competencias}")

    metricas = []
    for competencia in competencias:
        if not arquivo_existe_no_ftp(competencia):
            continue
        metricas.append(_baixar_e_extrair(competencia))

    baixadas = [m["competencia"] for m in metricas]
    logger.info(f"Backfill concluído. Competências efetivamente baixadas: {baixadas}")

    if baixadas:
        logger.info(f"Transformando {len(baixadas)} competência(s) com dbt...")
        _transformar(baixadas)
    else:
        logger.info("Nenhuma competência foi baixada, pulando dbt.")
    registrar_metricas(metricas, inicio)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "backfill":
        ano = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
        backfill_caged(ano)
    else:
        print("Uso: python flows/ingest_caged.py backfill <ano>")
        print(
            "O agendamento diário roda via 'prefect deploy' + worker "
            "(ver start.sh), não mais via .serve() direto."
        )
        sys.exit(1)
