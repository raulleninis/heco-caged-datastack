"""
Verificador determinístico do texto do boletim com IA (F19 parte 3).

Regra central do projeto: números nunca são calculados pelo LLM. Todo número do texto tem de
existir na tabela `numeros` dos fatos (flows/fatos.py), a menos de formatação:

- formato brasileiro: 25.439 | 0,33% | R$ 1.661,00 | 25,4 mil;
- sinal: "queda de 83" para um saldo de −83 (o texto costuma dizer o sentido por extenso);
- arredondamento: percentuais com 0, 1 ou 2 casas; reais com 0 ou 2 casas; "mil" com 0 ou 1.

Fica de fora da checagem o que não é dado: anos (2019 a 2035) e inteiros de 1 a 12 (meses,
"três fatores", "12 meses"). O custo dessa folga: um "5 vínculos" inventado passaria; um
percentual ou um saldo inventado, não.

Também sinaliza forma jurídica de empresa ou CNPJ no texto: o boletim nunca identifica empresas
(D10). É um aviso para a revisão humana, não uma prova.
"""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Número no formato brasileiro, com milhar em ponto e decimal em vírgula, com sinal opcional
# (hífen ou sinal de menos tipográfico). Não pega dígitos colados em letras (ex.: "CNAE 82" pega
# 82, mas "F19" não).
_NUMERO = re.compile(r"(?<![\w.,])[−-]?\d{1,3}(?:\.\d{3})+(?:,\d+)?(?![\w])|(?<![\w.,])[−-]?\d+(?:,\d+)?(?![\w])")
_MIL = re.compile(r"\s*mil\b", re.IGNORECASE)
_EMPRESA = re.compile(r"\b(LTDA|Ltda|S\.A\.|S/A|EIRELI|CNPJ|ME\b|EPP\b)")


def _decimal(token: str) -> Decimal | None:
    t = token.replace("−", "-").replace(".", "").replace(",", ".")
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def _arredondar(v: Decimal, casas: int) -> Decimal:
    return v.quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP)


def permitidos(numeros: dict) -> tuple[set[Decimal], set[Decimal]]:
    """(valores aceitos, valores aceitos antes de 'mil') a partir da tabela de fatos."""
    aceitos, em_mil = set(), set()
    for item in numeros.values():
        v = item["valor"]
        if v is None or isinstance(v, bool):
            continue
        v = abs(Decimal(str(v)))
        unidade = item["unidade"]
        if unidade == "pct":
            aceitos |= {_arredondar(v, c) for c in (0, 1, 2)}
        elif unidade == "brl":
            aceitos |= {_arredondar(v, 2), _arredondar(v, 0)}
        else:
            aceitos.add(v)
            em_mil |= {_arredondar(v / 1000, 1), _arredondar(v / 1000, 0)}
    return aceitos, em_mil


def _livre(v: Decimal) -> bool:
    """Números que não são dado: anos e inteiros pequenos."""
    if v == v.to_integral_value():
        n = int(v)
        return 1 <= n <= 12 or 2019 <= n <= 2035
    return False


def verificar_texto(texto: str, numeros: dict) -> list[dict]:
    """Problemas do texto: números fora da tabela de fatos e possíveis identificações de empresa."""
    aceitos, em_mil = permitidos(numeros)
    problemas = []
    for m in _NUMERO.finditer(texto):
        valor = _decimal(m.group())
        if valor is None:
            continue
        valor = abs(valor)
        seguido_de_mil = bool(_MIL.match(texto, m.end()))
        if seguido_de_mil:
            ok = valor in em_mil or valor * 1000 in aceitos
        else:
            ok = valor in aceitos or _livre(valor)
        if not ok:
            problemas.append({
                "tipo": "numero_fora_dos_fatos",
                "numero": m.group() + (" mil" if seguido_de_mil else ""),
                "trecho": texto[max(0, m.start() - 60): m.end() + 40].replace("\n", " "),
            })
    for m in _EMPRESA.finditer(texto):
        problemas.append({
            "tipo": "possivel_identificacao",
            "numero": None,
            "trecho": texto[max(0, m.start() - 60): m.end() + 40].replace("\n", " "),
        })
    return problemas
