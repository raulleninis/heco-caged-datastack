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
"""

from ftplib import FTP
from pathlib import Path
from datetime import date

import py7zr
from prefect import flow, task, get_run_logger

FTP_HOST = "ftp.mtps.gov.br"
RAW_DIR = Path("/data/raw")
DBT_PROJECT_DIR = Path("/dbt")


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


@task(log_prints=True)
def competencias_ja_ingeridas() -> set[str]:
    """Competências (AAAAMM) que já têm .txt extraído em disco.

    Staging já materializa como table (F09), mas o .txt ainda não é
    deletado após dbt run — só o .7z é (F07 fase 1). Quando F07 fase 2
    passar a deletar o .txt também, este critério de detecção precisa
    mudar para consultar o warehouse (.duckdb) em vez do filesystem —
    senão toda execução vai achar que nada foi ingerido e re-baixar tudo.
    """
    logger = get_run_logger()
    extraido_dir = RAW_DIR / "extraido"

    ingeridas = set()
    if extraido_dir.exists():
        for txt_file in extraido_dir.glob("CAGEDMOV*.txt"):
            ingeridas.add(txt_file.stem.replace("CAGEDMOV", ""))

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
def run_dbt(comando: list[str], dbt_vars: dict | None = None) -> None:
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


def _transformar(baixadas: list[str]) -> None:
    """Roda a staging incrementalmente (uma competência por vez, ~500MB de
    pico por execução, não ~3GB de uma vez — ver comentário em
    stg_caged_movimentacoes.sql) e depois materializa o mart (pequeno,
    processa tudo de uma vez sem risco de memória) e os testes."""
    logger = get_run_logger()
    for competencia in baixadas:
        logger.info(f"Transformando staging para {competencia}...")
        run_dbt(
            ["run", "--select", "stg_caged_movimentacoes"],
            dbt_vars={"competencia_arquivo": competencia},
        )

    logger.info("Materializando mart...")
    run_dbt(["run", "--select", "mart_caged_mensal_grupamento"])
    run_dbt(["test"])


@flow(name="ingest-caged", log_prints=True)
def ingest_caged():
    logger = get_run_logger()
    candidatos = meses_candidatos(meses_para_tras=6)
    ingeridas = competencias_ja_ingeridas()

    faltantes = [c for c in candidatos if c not in ingeridas and arquivo_existe_no_ftp(c)]

    if not faltantes:
        logger.info("Nenhuma competência faltante nos últimos 6 meses. Encerrando.")
        return

    logger.info(f"Competências faltantes (últimos 6 meses): {faltantes}")

    baixadas = []
    for competencia in faltantes:
        logger.info(f"Processando competência {competencia}...")
        arquivo = baixar_arquivo(competencia)
        extrair_7z(arquivo)
        deletar_arquivo_7z(arquivo)
        baixadas.append(competencia)

    logger.info(f"Ingestão concluída. Competências baixadas: {baixadas}")
    _transformar(baixadas)


@flow(name="backfill-caged", log_prints=True)
def backfill_caged(ano: int = 2026):
    logger = get_run_logger()
    competencias = competencias_do_ano(ano)
    logger.info(f"Competências candidatas para {ano}: {competencias}")

    baixadas = []
    for competencia in competencias:
        if not arquivo_existe_no_ftp(competencia):
            continue
        arquivo = baixar_arquivo(competencia)
        extrair_7z(arquivo)
        deletar_arquivo_7z(arquivo)
        baixadas.append(competencia)

    logger.info(f"Backfill concluído. Competências efetivamente baixadas: {baixadas}")

    if baixadas:
        logger.info(f"Transformando {len(baixadas)} competência(s) com dbt...")
        _transformar(baixadas)
    else:
        logger.info("Nenhuma competência foi baixada, pulando dbt.")


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
