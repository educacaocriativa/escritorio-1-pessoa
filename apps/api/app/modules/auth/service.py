"""Regras de negócio do auth: registro de tenant e autenticação."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.modules.auth.models import Tenant, User
from app.modules.auth.schemas import RegisterRequest


class AuthError(Exception):
    """Erro de negócio do auth (mapeado para HTTP 4xx no router)."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def register_tenant(db: Session, data: RegisterRequest) -> tuple[Tenant, User]:
    """Cria um Tenant novo + seu usuário owner. Falha se slug ou e-mail já existirem.

    Os checks prévios dão mensagens amigáveis; as UNIQUE constraints do banco são a fonte de
    verdade contra corrida (TOCTOU) — um IntegrityError concorrente também vira 409.
    """
    email = str(data.email).lower()
    if db.scalar(select(Tenant).where(Tenant.slug == data.slug)):
        raise AuthError("Este subdomínio já está em uso", 409)
    if db.scalar(select(User).where(User.email == email)):
        raise AuthError("Este e-mail já está cadastrado", 409)

    tenant = Tenant(slug=data.slug, legal_name=data.legal_name, document=data.document)
    db.add(tenant)
    db.flush()  # garante tenant.id

    owner = User(
        tenant_id=tenant.id,
        email=email,
        name=data.name,
        password_hash=hash_password(data.password),
        role="owner",
        allowed_modules=[],
    )
    db.add(owner)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise AuthError("Subdomínio ou e-mail já cadastrado", 409) from e
    db.refresh(tenant)
    db.refresh(owner)
    return tenant, owner


def authenticate(db: Session, email: str, password: str) -> tuple[Tenant, User]:
    """Valida credenciais. Mensagem genérica para não revelar se o e-mail existe."""
    user = db.scalar(select(User).where(User.email == email.lower()))
    if not user or not verify_password(password, user.password_hash):
        raise AuthError("E-mail ou senha inválidos", 401)
    if not user.is_active:
        raise AuthError("Conta desativada", 403)
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None:
        raise AuthError("Tenant não encontrado", 404)
    return tenant, user
