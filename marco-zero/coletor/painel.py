"""Coleta pública do Novo Caged. Não depende das capturas da auditoria original."""
import json
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

import requests

MEASURES = ['Admitidos', 'Desligados', 'Saldo', 'Estoque Mensal']
FIELDS = ['admissoes', 'desligamentos', 'saldo', 'estoque']


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.strip().casefold())
                   if not unicodedata.combining(c))


def column(source, name):
    return {'Column': {'Expression': {'SourceRef': {'Source': source}}, 'Property': name}}


def select_column(source, name):
    return {**column(source, name), 'Name': source + '.' + name}


def filter_values(source, name, values):
    def literal(value):
        return str(value) + 'L' if isinstance(value, int) else "'" + value.replace("'", "''") + "'"
    return {'Condition': {'In': {'Expressions': [column(source, name)],
            'Values': [[{'Literal': {'Value': literal(v)}}] for v in values]}}}


def decode(body):
    """Decodifica tabelas planas DSR; preserva zero, negativos e null distintos.

    Falha em layouts não suportados, limites ou continuações. Nunca publica uma
    amostra truncada como se fosse a série completa.
    """
    try:
        result = body['results'][0]['result']
        if 'error' in result:
            raise ValueError(str(result['error']))
        data = result['data']
        datasets = data['dsr']['DS']
        if len(datasets) != 1:
            raise ValueError('Mais de um dataset DSR; formato não suportado.')
        ds = datasets[0]
        # IC é um metadado presente em respostas completas; não é sinal de truncamento.
        for container in (data, ds):
            if container.get('RT') or container.get('RestartTokens'):
                raise ValueError('Consulta paginada. Reduza o recorte; falta implementar a continuação.')
        phases = ds.get('PH', [])
        if len(phases) != 1 or set(phases[0]) != {'DM0'}:
            raise ValueError('Estrutura DSR mudou; revisar o decodificador.')
        rows, previous, schema = [], None, None
        for row in phases[0]['DM0']:
            schema = row.get('S', schema)
            if not schema:
                raise ValueError('Resposta sem esquema.')
            if set(row) - {'S', 'C', 'R', 'Ø'} - {s['N'] for s in schema}:
                raise ValueError('Metadados de linha desconhecidos: ' + str(set(row)))
            repeat, nulls = row.get('R', 0), row.get('Ø', 0)
            if repeat & nulls or (repeat and previous is None):
                raise ValueError('Máscaras DSR inválidas.')
            cells, values = iter(row.get('C', [])), []
            for i, field in enumerate(schema):
                value = (previous[i] if repeat & (1 << i) else
                         None if nulls & (1 << i) else row[field['N']] if field['N'] in row else next(cells))
                values.append(value)
            sentinel = object()
            if next(cells, sentinel) is not sentinel:
                raise ValueError('Células excedentes na resposta.')
            previous = values
            rows.append([ds['ValueDicts'][s['DN']][v] if v is not None and 'DN' in s else v
                         for s, v in zip(schema, values)])
        return rows
    except (KeyError, IndexError, StopIteration, TypeError) as exc:
        raise ValueError('Resposta Power BI incompatível. Consulte o JSON de evidência.') from exc


def discover(url, directory, browser_name='chromium'):
    """Abre só a página pública e captura modelo/esquema, sem cliques por coordenadas."""
    from playwright.sync_api import sync_playwright
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    found = {}

    def capture(response):
        if '/public/reports/' not in response.url:
            return
        if 'modelsAndExploration' not in response.url and 'conceptualschema' not in response.url:
            return
        try:
            payload = response.json()
            key = 'modelo' if 'modelsAndExploration' in response.url else 'schema'
            save_json(directory / (key + '.json'), payload)
            found[key] = payload
            if key == 'modelo':
                found['model_url'] = response.url
                found['resource_key'] = response.request.headers.get('x-powerbi-resourcekey')
        except Exception as exc:
            found['erro_captura'] = str(exc)

    with sync_playwright() as p:
        kwargs = {'headless': True}
        if browser_name != 'chromium':
            kwargs['channel'] = browser_name
        browser = p.chromium.launch(**kwargs)
        page = browser.new_page()
        page.on('response', capture)
        page.goto(url, wait_until='domcontentloaded', timeout=90000)
        for _ in range(45):
            if 'modelo' in found and 'schema' in found:
                break
            page.wait_for_timeout(1000)
        (directory / 'pagina.txt').write_text(page.locator('body').inner_text(), encoding='utf-8')
        browser.close()
    if 'modelo' not in found or 'schema' not in found:
        raise ValueError('Não foi possível descobrir modelo/esquema. Veja descoberta/pagina.txt.')
    models = found['modelo']['models']
    if len(models) != 1:
        raise ValueError('Painel com múltiplos modelos; seleção manual necessária.')
    model = models[0]
    if not found.get('resource_key'):
        found['resource_key'] = urlsplit(found['model_url']).path.split('/public/reports/')[1].split('/')[0]
    origin = urlsplit(found['model_url'])
    session = {'endpoint': origin.scheme + '://' + origin.netloc + '/public/reports/querydata?synchronous=true',
               'model_url': found['model_url'], 'model_id': model['id'],
               'resource_key': found['resource_key'], 'refresh': model.get('LastRefreshTime'),
               'painel_url': url}
    save_json(directory / 'sessao.json', session)
    entities = found['schema']['schemas'][0]['schema']['Entities']
    available = {e['Name']: {prop['Name'] for prop in e['Properties']} for e in entities}
    required = {'TabelaDeDatas': {'competência'}, 'Econômico': {'Grande Grupamento'},
                'Medidas': set(MEASURES),
                'Geográfico': {'Código Município', 'Município', 'Código UF', 'UF'}}
    for entity, properties in required.items():
        if not properties <= available.get(entity, set()):
            raise ValueError('O esquema mudou: campos esperados não encontrados em ' + entity)
    return session


class PublicPanel:
    def __init__(self, session, evidence):
        self.session = session
        self.evidence = Path(evidence)
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.http = requests.Session()
        self.http.headers.update({'x-powerbi-resourcekey': session['resource_key'],
                                  'Content-Type': 'application/json', 'Referer': 'https://app.powerbi.com/'})

    def query(self, name, selects, where):
        query = {'Version': 2,
                 'From': [{'Name': s, 'Entity': e, 'Type': 0} for s, e in
                          [('d', 'TabelaDeDatas'), ('e', 'Econômico'), ('m', 'Medidas'), ('g', 'Geográfico')]],
                 'Select': selects, 'Where': where}
        command = {'SemanticQueryDataShapeCommand': {'Query': query,
                   'Binding': {'Primary': {'Groupings': [{'Projections': list(range(len(selects)))}]},
                               'DataReduction': {'DataVolume': 4, 'Primary': {'Window': {'Count': 10000}}},
                               'Version': 1}, 'ExecutionMetricsKind': 1}}
        body = {'version': '1.0.0', 'queries': [{'Query': {'Commands': [command]}, 'QueryId': ''}],
                'cancelQueries': [], 'modelId': self.session['model_id']}
        path = self.evidence / (name + '.json')
        response = None
        for attempt in range(3):
            try:
                response = self.http.post(self.session['endpoint'], json=body, timeout=90)
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                break
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        save_json(path, {'request': body, 'status': response.status_code, 'response': response.text})
        response.raise_for_status()
        rows = decode(response.json())
        if len(rows) >= 10000:
            raise ValueError('Limite da consulta atingido; não é seguro exportar resultados parciais.')
        return rows

    def catalog(self, uf):
        return self.query('municipios_' + str(uf),
                          [select_column('g', 'Código Município'), select_column('g', 'Município')],
                          [filter_values('g', 'Código UF', [uf])])

    def dates(self):
        measure = {'Measure': {'Expression': {'SourceRef': {'Source': 'm'}}, 'Property': 'Admitidos'},
                   'Name': 'Medidas.Admitidos'}
        return sorted(int(row[0]) for row in self.query('competencias',
                      [select_column('d', 'competência'), measure], [])
                      if row[0] is not None and row[1] is not None)

    def metrics(self, territory, month, grouped):
        selects = [select_column('e', 'Grande Grupamento')] if grouped else []
        selects += [{'Measure': {'Expression': {'SourceRef': {'Source': 'm'}}, 'Property': p},
                     'Name': 'Medidas.' + p} for p in MEASURES]
        prop = 'Código UF' if territory['tipo'] == 'uf' else 'Código Município'
        return self.query(f"{territory['tipo']}_{territory['codigo']}_{month}_" + ('grupos' if grouped else 'total'),
                          selects, [filter_values('g', prop, [territory['codigo']]),
                                    filter_values('d', 'competência', [month])])

    def check_refresh(self):
        response = self.http.get(self.session['model_url'], timeout=60)
        response.raise_for_status()
        body = response.json()
        save_json(self.evidence / 'modelo_ao_final.json', body)
        model = body['models'][0]
        if model['id'] != self.session['model_id'] or model.get('LastRefreshTime') != self.session['refresh']:
            raise ValueError('O painel foi atualizado durante a coleta. Recomece para evitar misturar versões.')
