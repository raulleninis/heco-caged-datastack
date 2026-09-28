"""Confere microdados atuais contra as stagings municipais, sem alterar o DuckDB."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from ftplib import FTP
from pathlib import Path
import uuid

from painel import save_json


def main():
    import duckdb
    import py7zr
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duckdb', required=True)
    parser.add_argument('--municipio', required=True, type=int, help='Código Caged de 6 dígitos.')
    parser.add_argument('--uf', required=True, type=int)
    parser.add_argument('--competencias-mov', nargs='+', type=int, default=[])
    parser.add_argument('--todos-ajustes', action='store_true', help='Confere todos os FOR/EXC registrados em ingestao_arquivos.')
    parser.add_argument('--saida', default='saida')
    args = parser.parse_args()
    if not args.competencias_mov and not args.todos_ajustes:
        parser.error('Escolha --competencias-mov e/ou --todos-ajustes.')
    database = Path(args.duckdb).expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    conn = duckdb.connect(str(database), read_only=True)
    tasks = {('MOV', m) for m in args.competencias_mov}
    if args.todos_ajustes:
        tasks |= {(kind, int(month)) for kind, month in conn.execute(
                  "SELECT tipo, competencia_arquivo FROM ingestao_arquivos WHERE tipo IN ('FOR','EXC')").fetchall()}
    if any(not 1 <= m % 100 <= 12 for _, m in tasks):
        raise ValueError('Competência inválida.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid.uuid4().hex[:6]
    out = Path(args.saida).resolve() / ('auditoria-ftp-' + stamp)
    out.mkdir(parents=True)
    save_json(out / 'status.json', {'status': 'em_andamento'})
    print('Pasta:', out, flush=True)
    tables = {'MOV': 'stg_caged_movimentacoes', 'FOR': 'stg_caged_fora_do_prazo', 'EXC': 'stg_caged_exclusoes'}
    checks = []
    try:
        with FTP('ftp.mtps.gov.br', timeout=120, encoding='latin-1') as ftp:
            ftp.login()
            for kind, month in sorted(tasks, key=lambda item: (item[1], item[0])):
                directory = out / f'{kind}{month}'
                directory.mkdir()
                ftp.cwd(f'/pdet/microdados/NOVO CAGED/{month // 100}/{month}')
                listing = []
                ftp.retrlines('LIST', listing.append)
                (directory / 'listagem.txt').write_text('\n'.join(listing), encoding='utf-8')
                stem = f'CAGED{kind}{month}'
                archive = directory / (stem + '.7z')
                with archive.open('wb') as f:
                    ftp.retrbinary('RETR ' + archive.name, f.write)
                with archive.open('rb') as f:
                    sha256 = hashlib.file_digest(f, 'sha256').hexdigest()
                with py7zr.SevenZipFile(archive) as z:
                    if stem + '.txt' not in z.getnames():
                        raise ValueError('Arquivo TXT esperado ausente no 7z: ' + stem)
                    z.extract(path=directory, targets=[stem + '.txt'])
                txt = directory / (stem + '.txt')
                query = '''SELECT CAST("competênciamov" AS BIGINT), CAST(subclasse AS BIGINT),
                           "seção", CAST("saldomovimentação" AS BIGINT), COUNT(*)
                           FROM read_csv_auto(?, delim=';', all_varchar=true)
                           WHERE CAST(uf AS BIGINT)=? AND CAST("município" AS BIGINT)=?
                           GROUP BY 1,2,3,4'''
                raw = {tuple(r[:4]): r[4] for r in conn.execute(query, [str(txt), args.uf, args.municipio]).fetchall()}
                month_field = 'competencia_mov' if kind == 'MOV' else 'competencia_arquivo'
                query = f'''SELECT competencia_mov,subclasse,secao,saldo_movimentacao,count(*)
                            FROM {tables[kind]} WHERE {month_field}=? AND uf=? AND municipio=? GROUP BY 1,2,3,4'''
                local = {tuple(r[:4]): r[4] for r in conn.execute(query, [month, args.uf, args.municipio]).fetchall()}
                differences = [[*k, local.get(k, 0), raw.get(k, 0)] for k in sorted(set(local) | set(raw))
                               if local.get(k, 0) != raw.get(k, 0)]
                result = {'tipo': kind, 'competencia_arquivo': month, 'municipio': args.municipio,
                          'sha256': sha256, 'linhas_local': sum(local.values()), 'linhas_ftp': sum(raw.values()),
                          'diferencas': differences,
                          'colunas_diferencas': ['competencia_mov', 'subclasse', 'secao', 'sinal', 'local', 'ftp']}
                checks.append(result)
                save_json(directory / 'conferencia.json', result)
                save_json(out / 'resultados.json', checks)
                print('Conferido:', kind, month, 'diferenças:', len(differences), flush=True)
        save_json(out / 'status.json', {'status': 'concluido', 'arquivos': len(checks),
                  'arquivos_divergentes': sum(bool(c['diferencas']) for c in checks),
                  'limite': 'Igualdade das contagens por competência, CNAE, seção e sinal; não é identidade de cada evento. '
                            'A lista de ajustes vem do manifesto local; não comprova ausência de arquivos ainda não ingeridos.'})
    except Exception as exc:
        save_json(out / 'status.json', {'status': 'falhou', 'erro': str(exc)})
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
