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
from app.core.subdomain import extract_tenant_slug, get_tenant_by_subdomain
from app.db.session import SessionLocal, get_db, tenant_session


@dataclass
class CurrentUser:
    user_id: str
    tenant_id: str
    role: str
    allowed_modules: list[str]
    is_platform_admin: bool = False

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
        is_platform_admin=bool(payload.get("is_platform_admin", False)),
    )


def require_platform_admin(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """Bloqueia quem não é Master (Nível 1). Revalida no banco — não confia só no claim do
    token (que vive 7 dias); um admin rebaixado/desativado perde acesso imediatamente."""
    from app.modules.auth.models import User

    db_user = db.get(User, user.user_id)
    if db_user is None or not db_user.is_active or not db_user.is_platform_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Acesso restrito ao administrador da plataforma"
        )
    return user


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


__all__ = [
    "CurrentUser",
    "get_current_user",
    "get_tenant_db",
    "require_module",
    "require_platform_admin",
    "SessionLocal",
    # Resolução de tenant por subdomínio (Story 4.4). ⚠️ Reexportado por conveniência, mas
    # NUNCA use para isolamento/RLS — o Host header é controlável pelo cliente. Só branding/UX
    # em rotas públicas (ver app/core/subdomain.py).
    "extract_tenant_slug",
    "get_tenant_by_subdomain",
]
