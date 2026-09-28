"""Comparação opcional, somente leitura. Nunca reaplica FOR/EXC ao mart reconciliado."""
import csv
from pathlib import Path

from painel import FIELDS, save_json


def identifier(name):
    if not isinstance(name, str) or not name:
        raise ValueError('Nome SQL inválido.')
    return '"' + name.replace('"', '""') + '"'


def compare(config, database, official, directory):
    import duckdb
    database = Path(database).expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(f'DuckDB não encontrado: {database}')
    directory = Path(directory)
    columns = config['colunas']
    table = '.'.join(identifier(p) for p in config['tabela'].split('.'))
    conn = duckdb.connect(str(database), read_only=True)
    try:
        info = conn.execute(f'DESCRIBE {table}').fetchall()
        existing = {row[0] for row in info}
        required = {v for v in columns.values() if v}
        if not required <= existing:
            raise ValueError('Colunas ausentes no DuckDB: ' + ', '.join(sorted(required - existing)))
        if not columns.get('competencia') or not columns.get('grupamento'):
            raise ValueError('Configure as colunas de competência e grupamento.')
        metrics = [field for field in FIELDS if columns.get(field)]
        if not metrics:
            raise ValueError('Nenhuma medida local configurada.')
        codes = sorted({r['codigo_territorio'] for r in official if r['tipo_territorio'] == 'municipio'})
        if not codes:
            raise ValueError('A coleta contém somente UFs; este comparador requer ao menos um município.')
        confirmed = None
        if not columns.get('municipio'):
            declared = config.get('municipio_da_base')
            if not declared:
                raise ValueError('Mart sem município: informe comparacao.municipio_da_base; não presumimos o território.')
            codes = [int(declared)] if int(declared) in codes else []
            if not codes:
                raise ValueError('O município declarado para a base não está entre os alvos coletados.')
            # Se houver a staging conhecida, confira a declaração com os dados reais. Staging de
            # um município só confirma a declaração; staging de UF inteira (vários municípios)
            # só prova que o município existe nela, não que o mart seja dele.
            available_tables = {r[0] for r in conn.execute('SHOW TABLES').fetchall()}
            if 'stg_caged_movimentacoes' in available_tables:
                staging_columns = {r[0] for r in conn.execute('DESCRIBE stg_caged_movimentacoes').fetchall()}
                if 'municipio' in staging_columns:
                    actual = {int(r[0]) for r in conn.execute('SELECT DISTINCT municipio FROM stg_caged_movimentacoes').fetchall() if r[0] is not None}
                    if int(declared) not in actual:
                        raise ValueError(f'Município declarado {declared} ausente da staging ({len(actual)} municípios).')
                    confirmed = actual == {int(declared)}
        months = sorted({r['competencia'] for r in official})
        qmarks = ','.join('?' for _ in months)
        # TRY_CAST: a coluna de território pode ser texto (ex.: mart_estoque.territorio, que
        # também traz a UF como '28'); a comparação é sempre com o código numérico de 6 dígitos.
        scope_expr = (f'TRY_CAST({identifier(columns["municipio"])} AS BIGINT)' if columns.get('municipio')
                      else str(codes[0]))
        selects = [scope_expr, identifier(columns['competencia']), identifier(columns['grupamento'])]
        selects += [f'SUM({identifier(columns[f])})' for f in metrics]
        predicate = f'{identifier(columns["competencia"])} IN ({qmarks})'
        params = list(months)
        if columns.get('municipio'):
            predicate += f' AND {scope_expr} IN (' + ','.join('?' for _ in codes) + ')'
            params += codes
        query = f'SELECT {", ".join(selects)} FROM {table} WHERE {predicate} GROUP BY 1,2,3'
        local_rows = conn.execute(query, params).fetchall()
        save_json(directory / 'schema_duckdb.json', {'tabela': config['tabela'], 'colunas': info,
                  'consulta': query, 'parametros': params, 'modo': 'somente_leitura'})
    finally:
        conn.close()
    names = config.get('mapa_grupamentos', {})
    local = {}
    for code, month, group, *values in local_rows:
        if group is None or str(group).strip().upper() in ('TOTAL', 'TODOS'):
            raise ValueError('Mart contém grupamento nulo ou total pré-agregado. Configure uma tabela sem dupla contagem.')
        group = names.get(str(group).strip(), str(group).strip())
        key = (int(code), int(month), group)
        if key in local:
            raise ValueError('Mapeamento de grupamentos produziu duplicidade: ' + str(key))
        local[key] = dict(zip(metrics, values))
    for code, month in sorted({k[:2] for k in local}):
        rows = [v for k, v in local.items() if k[:2] == (code, month)]
        local[(code, month, 'TOTAL')] = {
            f: sum(r[f] for r in rows if r[f] is not None) if any(r[f] is not None for r in rows) else None
            for f in metrics}
    reference = {(r['codigo_territorio'], r['competencia'], r['grupamento']): r for r in official
                 if r['tipo_territorio'] == 'municipio' and r['codigo_territorio'] in codes}
    rows = []
    for key in sorted(set(local) | set(reference)):
        a, b = local.get(key), reference.get(key)
        for metric in metrics:
            vlocal, vofficial = a.get(metric) if a else None, b.get(metric) if b else None
            status = ('AUSENTE_LOCAL' if a is None else 'AUSENTE_PAINEL' if b is None else
                      'IGUAL' if vlocal == vofficial else 'NULO_VS_VALOR' if vlocal is None or vofficial is None else 'DIVERGENTE')
            delta = vlocal - vofficial if vlocal is not None and vofficial is not None else None
            rows.append([*key, metric, vlocal, vofficial, delta, status])
    with (directory / 'comparacao_duckdb.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(['codigo_municipio', 'competencia', 'grupamento', 'medida', 'local', 'oficial', 'delta_local_menos_oficial', 'situacao'])
        writer.writerows(rows)
    differences = [r for r in rows if r[-1] != 'IGUAL']
    result = {'municipios_comparados': codes, 'medidas_comparadas': metrics,
              'municipio_da_base_confirmado_pela_staging': confirmed,
              'medidas_sem_coluna_local': [f for f in FIELDS if f not in metrics],
              'comparacoes': len(rows), 'diferencas': len(differences),
              'competencias_com_diferenca': sorted({r[1] for r in differences}),
              'ufs_nao_comparadas': True, 'definicao_delta': 'local menos oficial',
              'observacao': 'Ausência e null não são imputados como zero. FOR/EXC já estão no mart configurado.'}
    save_json(directory / 'validacao_duckdb.json', result)
    return result
