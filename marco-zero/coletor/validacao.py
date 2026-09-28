"""Validações determinísticas: a IA interpreta evidências, não calcula os números."""
from painel import FIELDS


def validate_pair(groups, totals, context):
    if len(totals) != 1 or len(totals[0]) != 4:
        raise ValueError(f'{context}: total ausente ou inesperado: {totals}')
    seen = set()
    total = totals[0]
    if all(value is None for value in total):
        raise ValueError(f'{context}: todas as medidas estão vazias; confirme disponibilidade do recorte.')
    for row in groups:
        if len(row) != 5 or row[0] in seen:
            raise ValueError(f'{context}: grupamento duplicado ou linha inválida.')
        seen.add(row[0])
    for row in [total] + [r[1:] for r in groups]:
        if any(v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v)
               for v in row):
            raise ValueError(f'{context}: medida não inteira: {row}')
        a, d, s, _ = row
        if (a or 0) - (d or 0) != (s or 0):
            raise ValueError(f'{context}: saldo incoerente: {row}')
    for i, field in enumerate(FIELDS[:3]):
        if sum(row[i + 1] or 0 for row in groups) != (total[i] or 0):
            raise ValueError(f'{context}: soma de {field} não coincide com o total independente.')
    missing = sum(row[4] is None for row in groups)
    partial_sum = sum(row[4] or 0 for row in groups)
    return {'contexto': context, 'grupamentos': len(groups), 'saldo_conferido': True,
            'movimentos_totais_conferidos': True, 'estoques_vazios': missing,
            'soma_estoques_disponiveis': partial_sum, 'estoque_total_oficial': total[3],
            'estoque_exige_observacao': bool(missing or partial_sum != total[3])}
