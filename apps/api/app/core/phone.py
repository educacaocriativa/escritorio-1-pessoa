"""Normalização de telefone brasileiro para COMPARAÇÃO (dedup de contato).

Módulo utilitário do núcleo, mesma convenção de `validators.py`: sem I/O, pura
normalização, chamável de qualquer serviço ou schema.

O resultado NÃO substitui o telefone que a pessoa digitou — ele vive ao lado, em
`clients.phone_key`. `clients.phone` continua guardando `"(11) 99999-8888"` (evidência do
que chegou) e `phone_key` guarda `"5511999998888"` (a forma comparável). Mesmo par
`raw_description`/`user_description` de `bank_transactions`.

LIMITE CONHECIDO: o produto é BR-only, então um número estrangeiro de 10-11 dígitos é
normalizado como se fosse brasileiro. Não há campo de país para desambiguar, e inventar uma
heurística seria pior que o erro que ela evitaria.
"""
from __future__ import annotations

import re

_NON_DIGITS = re.compile(r"\D")

# Primeiro dígito do número LOCAL (depois do DDD): 6-9 é celular, 2-5 é fixo. É a faixa da
# Anatel, e é o que permite inserir o 9º dígito só onde ele de fato existe — sem isso, um
# fixo "11 3333-4444" e um celular "11 93333-4444" colapsariam na mesma chave.
_MOBILE_FIRST_DIGITS = "6789"


def normalize_br(raw: str | None) -> str | None:
    """`"(11) 9999-8888"` -> `"5511999998888"`. `None` quando não encaixa em formato BR."""
    digits = _NON_DIGITS.sub("", raw or "")
    if not digits:
        return None

    # Código de país presente? Só tira o "55" se o que sobra for um número BR plausível —
    # senão um fixo de DDD 55 (Pelotas/RS) perderia o próprio DDD.
    if digits.startswith("55") and len(digits) - 2 in (10, 11):
        digits = digits[2:]

    if len(digits) not in (10, 11):
        return None

    ddd, local = digits[:2], digits[2:]
    if ddd[0] == "0":
        # "011 99999-8888": o zero de operadora não faz parte do DDD, e adivinhar qual
        # dígito sobra seria chute. Não deduplica por telefone.
        return None

    if len(local) == 8 and local[0] in _MOBILE_FIRST_DIGITS:
        local = "9" + local  # celular pré-2016 — ganha o 9º dígito

    return "55" + ddd + local
