"""
Flows de ingestão do Novo CAGED (PDET / Ministério do Trabalho).

Dois flows neste arquivo:
- ingest_caged: roda no cron diário, busca só a competência mais recente.
- backfill_caged: roda sob demanda, busca todas as competências de um ano
  até a mais recente já publicada.
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
def run_dbt(comando: list[str]) -> None:
    import subprocess
    logger = get_run_logger()
    cmd = ["dbt", *comando, "--project-dir", str(DBT_PROJECT_DIR), "--profiles-dir", str(DBT_PROJECT_DIR)]
    logger.info(f"Executando: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    logger.info(result.stdout)
    if result.returncode != 0:
        logger.error(result.stderr)
        raise RuntimeError(f"dbt {' '.join(comando)} falhou")


@flow(name="ingest-caged", log_prints=True)
def ingest_caged():
    logger = get_run_logger()
    competencia = competencia_alvo()
    logger.info(f"Competência-alvo de hoje: {competencia}")

    if not arquivo_existe_no_ftp(competencia):
        logger.info("Encerrando sem erro -- tentamos de novo na próxima execução agendada.")
        return

    arquivo = baixar_arquivo(competencia)
    extrair_7z(arquivo)
    # run_dbt(["run"])
    # run_dbt(["test"])


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
        baixadas.append(competencia)

    logger.info(f"Backfill concluído. Competências efetivamente baixadas: {baixadas}")


if __name__ == "__main__":
    ingest_caged.serve(name="caged-pipeline", cron="0 3 * * *")
