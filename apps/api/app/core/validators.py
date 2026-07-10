"""Validação de documentos brasileiros (CPF/CNPJ).

Módulo utilitário do núcleo (`app/core/`), na mesma convenção de `security.py`/`tenancy.py`.
Sem I/O: pura validação/normalização, chamável de qualquer schema Pydantic.

Regra de produto: mensagens de erro voltadas ao usuário em PT-BR (ver CLAUDE.md §8).
"""
from __future__ import annotations

import re

_NON_DIGITS = re.compile(r"\D")


def normalize_document(raw: str) -> str:
    """Remove tudo que não é dígito. `"529.982.247-25"` -> `"52998224725"`."""
    return _NON_DIGITS.sub("", raw or "")


def _all_same(digits: str) -> bool:
    """True para sequências repetidas (`"00000000000"`, `"11111111111"`, ...)."""
    return len(set(digits)) == 1


def _cpf_check_digit(digits: str, length: int) -> int:
    """Dígito verificador do CPF: soma ponderada dos `length` primeiros dígitos.

    O peso começa em `length + 1` e decresce. Resto < 2 => 0, senão 11 - resto.
    """
    total = sum(int(digits[i]) * (length + 1 - i) for i in range(length))
    rest = total % 11
    return 0 if rest < 2 else 11 - rest


def validate_cpf(digits: str) -> bool:
    """Valida um CPF (só-dígitos): 11 dígitos, não-sequência, 2 DVs corretos."""
    if len(digits) != 11 or not digits.isdigit() or _all_same(digits):
        return False
    d1 = _cpf_check_digit(digits, 9)
    d2 = _cpf_check_digit(digits, 10)
    return d1 == int(digits[9]) and d2 == int(digits[10])


# Pesos oficiais dos dois dígitos verificadores do CNPJ.
_CNPJ_W1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
_CNPJ_W2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]


def _cnpj_check_digit(digits: str, weights: list[int]) -> int:
    total = sum(int(digits[i]) * weights[i] for i in range(len(weights)))
    rest = total % 11
    return 0 if rest < 2 else 11 - rest


def validate_cnpj(digits: str) -> bool:
    """Valida um CNPJ (só-dígitos): 14 dígitos, não-sequência, 2 DVs corretos."""
    if len(digits) != 14 or not digits.isdigit() or _all_same(digits):
        return False
    d1 = _cnpj_check_digit(digits, _CNPJ_W1)
    d2 = _cnpj_check_digit(digits, _CNPJ_W2)
    return d1 == int(digits[12]) and d2 == int(digits[13])


def validate_document(raw: str) -> str:
    """Normaliza e valida um CPF (11) ou CNPJ (14). Retorna a string só-dígitos.

    Levanta `ValueError` com mensagem em PT-BR se inválido. Pydantic converte esse
    `ValueError` de um `@field_validator` automaticamente em HTTP 422.
    """
    digits = normalize_document(raw)
    if len(digits) == 11:
        if not validate_cpf(digits):
            raise ValueError("CPF inválido")
        return digits
    if len(digits) == 14:
        if not validate_cnpj(digits):
            raise ValueError("CNPJ inválido")
        return digits
    raise ValueError("documento deve ter 11 (CPF) ou 14 (CNPJ) dígitos")
