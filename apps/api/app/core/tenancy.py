"""Resolução de tenant e dependências de autenticação para as rotas.

Toda rota autenticada de módulo de negócio deve depender de `get_tenant_db`, que entrega uma
sessão já fixada no tenant correto (RLS). Assim o isolamento é garantido pelo banco.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import SessionLocal, tenant_session


@dataclass
class CurrentUser:
    user_id: str
    tenant_id: str
    role: str
    allowed_modules: list[str]

    @property
    def is_ai(self) -> bool:
        return False


def get_current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token ausente")
    payload = decode_access_token(authorization.split(" ", 1)[1])
    if not payload or "sub" not in payload or "tenant_id" not in payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido")
    return CurrentUser(
        user_id=payload["sub"],
        tenant_id=payload["tenant_id"],
        role=payload.get("role", "owner"),
        allowed_modules=payload.get("allowed_modules", []),
    )


def get_tenant_db(user: CurrentUser = Depends(get_current_user)) -> Iterator[Session]:
    """Sessão isolada por tenant (RLS ligada). Use em rotas de módulos de negócio."""
    with tenant_session(user.tenant_id) as db:
        yield db


def require_module(module: str):
    """Dependency factory: bloqueia sub-usuário sem permissão ao módulo (RBAC)."""

    def _checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role == "owner" or not user.allowed_modules or module in user.allowed_modules:
            return user
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Sem acesso ao módulo '{module}'")

    return _checker


__all__ = ["CurrentUser", "get_current_user", "get_tenant_db", "require_module", "SessionLocal"]
