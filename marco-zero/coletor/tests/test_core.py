import json
import tempfile
import unittest
from pathlib import Path

from painel import decode
from marco_zero import select_months
from validacao import validate_pair
from warehouse import compare


class CoreTests(unittest.TestCase):
    def test_named_scalar_cells(self):
        ds = {'PH': [{'DM0': [{'S': [{'N': 'G0', 'DN': 'D0'}], 'G0': 0}]}],
              'ValueDicts': {'D0': ['Sergipe']}, 'IC': True}
        body = {'results': [{'result': {'data': {'dsr': {'DS': [ds]}}}}]}
        self.assertEqual(decode(body), [['Sergipe']])

    def test_decode_preserves_zero_negative_null_dictionary_and_repeat(self):
        ds = {'ValueDicts': {'D0': ['Comércio']}, 'PH': [{'DM0': [
            {'S': [{'N': 'G0', 'DN': 'D0'}, {'N': 'M0'}, {'N': 'M1'}, {'N': 'M2'}, {'N': 'M3'}],
             'C': [0, 0, 2, -2], 'Ø': 16},
            {'C': [3, -3, 9], 'R': 3}]}]}
        body = {'results': [{'result': {'data': {'dsr': {'DS': [ds]}}}}]}
        self.assertEqual(decode(body), [['Comércio', 0, 2, -2, None], ['Comércio', 0, 3, -3, 9]])

    def test_partial_response_is_rejected(self):
        body = {'results': [{'result': {'data': {'dsr': {'DS': [{'RT': ['next'], 'PH': [{'DM0': []}]}]}}}}]}
        with self.assertRaises(ValueError):
            decode(body)

    def test_months_and_unavailable_period(self):
        self.assertEqual(select_months({'inicio': 202001, 'fim': 'ultima_disponivel', 'meses_do_ano': [6, 12]},
                         [202006, 202012, 202106]), [202006, 202012, 202106])
        with self.assertRaises(ValueError):
            select_months({'competencias': [202612]}, [202607])

    def test_stock_null_does_not_become_balance(self):
        result = validate_pair([['Não Identificado', 0, 2, -2, None]], [[0, 2, -2, None]], 'exemplo')
        self.assertEqual(result['estoques_vazios'], 1)
        self.assertTrue(result['estoque_exige_observacao'])
        with self.assertRaises(ValueError):
            validate_pair([['Grupo', 0, 2, 2, 10]], [[0, 2, -2, 10]], 'erro')

    def test_local_read_only_comparison_does_not_apply_adjustments_again(self):
        import duckdb
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'test.duckdb'
            conn = duckdb.connect(str(path))
            conn.execute('CREATE TABLE mart (comp BIGINT, grupo VARCHAR, a BIGINT, d BIGINT, s BIGINT)')
            conn.execute("INSERT INTO mart VALUES (202607,'Serviços',0,2,-2)")
            conn.close()
            config = {'tabela': 'main.mart', 'municipio_da_base': 280480,
                      'colunas': {'competencia': 'comp', 'grupamento': 'grupo', 'admissoes': 'a',
                                  'desligamentos': 'd', 'saldo': 's', 'estoque': None, 'municipio': None}}
            official = [{'codigo_territorio': 280480, 'tipo_territorio': 'municipio',
                         'competencia': 202607, 'grupamento': g, 'admissoes': 0,
                         'desligamentos': 2, 'saldo': -2, 'estoque': None} for g in ['Serviços', 'TOTAL']]
            before = path.read_bytes()
            result = compare(config, path, official, root)
            self.assertEqual(result['diferencas'], 0)
            self.assertEqual(result['medidas_sem_coluna_local'], ['estoque'])
            self.assertEqual(before, path.read_bytes())

    def test_state_wide_staging_accepts_declared_municipality_without_confirming(self):
        import duckdb
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'test.duckdb'
            conn = duckdb.connect(str(path))
            conn.execute('CREATE TABLE stg_caged_movimentacoes (municipio BIGINT)')
            conn.execute('INSERT INTO stg_caged_movimentacoes VALUES (280480), (280030)')
            conn.execute('CREATE TABLE mart (comp BIGINT, grupo VARCHAR, s BIGINT)')
            conn.execute("INSERT INTO mart VALUES (202607,'Serviços',-2)")
            conn.close()
            config = {'tabela': 'main.mart', 'municipio_da_base': 280480,
                      'colunas': {'competencia': 'comp', 'grupamento': 'grupo', 'saldo': 's'}}
            official = [{'codigo_territorio': 280480, 'tipo_territorio': 'municipio', 'competencia': 202607,
                         'grupamento': g, 'saldo': -2} for g in ['Serviços', 'TOTAL']]
            result = compare(config, path, official, root)
            self.assertEqual(result['diferencas'], 0)
            self.assertFalse(result['municipio_da_base_confirmado_pela_staging'])
            with self.assertRaises(ValueError):
                compare({**config, 'municipio_da_base': 280670}, path,
                        [{**r, 'codigo_territorio': 280670} for r in official], root)

    def test_text_territory_column_with_state_row_compares_only_municipality(self):
        import duckdb
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'test.duckdb'
            conn = duckdb.connect(str(path))
            conn.execute('CREATE TABLE mart_estoque (territorio VARCHAR, comp BIGINT, grupo VARCHAR, e BIGINT)')
            conn.execute("INSERT INTO mart_estoque VALUES ('280480',202003,'Serviços',8817), ('28',202003,'Serviços',136319)")
            conn.close()
            config = {'tabela': 'main.mart_estoque',
                      'colunas': {'competencia': 'comp', 'grupamento': 'grupo', 'estoque': 'e',
                                  'municipio': 'territorio'}}
            official = [{'codigo_territorio': 280480, 'tipo_territorio': 'municipio', 'competencia': 202003,
                         'grupamento': g, 'estoque': 8817} for g in ['Serviços', 'TOTAL']]
            official.append({'codigo_territorio': 28, 'tipo_territorio': 'uf', 'competencia': 202003,
                             'grupamento': 'Serviços', 'estoque': 136319})
            result = compare(config, path, official, root)
            self.assertEqual(result['comparacoes'], 2)
            self.assertEqual(result['diferencas'], 0)


if __name__ == '__main__':
    unittest.main()
