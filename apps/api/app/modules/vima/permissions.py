"""Filtro de módulo no nível do DADO.

`core.tenancy.require_module` é guard de ROTA — bloqueia acesso a um endpoint. O briefing é
*uma* rota que atravessa oito módulos, então precisa de um filtro diferente: quais fatos,
ausências e tendências este usuário pode ver.

A regra de decisão é a MESMA de `require_module` (owner vê tudo; lista vazia vê tudo; senão
só o que está na lista). Divergir daria dois significados para `allowed_modules` e o bug
apareceria como vazamento, não como erro.

⚠️ O filtro decide quais REGRAS RODAM, não quais resultados aparecem. Para um usuário só de
CRM a regra de tendência financeira não é executada — não é calculada e escondida. Mais barato,
e elimina a classe inteira de bug em que um dado proibido vaza porque alguém esqueceu de
aplicar o filtro na saída.
"""
from __future__ import annotations

from app.core.tenancy import CurrentUser


def modulos_permitidos(user: CurrentUser) -> set[str] | None:
    """Devolve o conjunto de módulos visíveis, ou `None` quando não há restrição."""
    if user.role == "owner" or not user.allowed_modules:
        return None
    return set(user.allowed_modules)


def pode_ver(user: CurrentUser, module: str) -> bool:
    permitidos = modulos_permitidos(user)
    return permitidos is None or module in permitidos
