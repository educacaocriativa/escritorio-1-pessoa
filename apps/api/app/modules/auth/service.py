"""Regras de negócio do auth: registro de tenant e autenticação."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import (
    generate_reset_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.modules.auth.models import Tenant, User
from app.modules.auth.schemas import RegisterRequest

RESET_TOKEN_TTL = timedelta(hours=1)


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


def request_password_reset(db: Session, email: str) -> str | None:
    """Gera um token de redefinição para o e-mail, se existir uma conta ativa.

    Retorna o token CRU (para o chamador entregar via e-mail/link) ou None se não há conta.
    O router responde sempre genérico — nunca revela se o e-mail existe.
    """
    user = db.scalar(select(User).where(User.email == email.lower()))
    if not user or not user.is_active:
        return None
    raw, hashed = generate_reset_token()
    user.reset_token_hash = hashed
    user.reset_token_expires = datetime.now(UTC) + RESET_TOKEN_TTL
    db.commit()
    return raw


def reset_password(db: Session, token: str, new_password: str) -> None:
    """Redefine a senha a partir de um token válido e não expirado."""
    user = db.scalar(select(User).where(User.reset_token_hash == hash_token(token)))
    expires = user.reset_token_expires if user else None
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)  # SQLite guarda naive; normaliza p/ comparar
    if user is None or expires is None or expires < datetime.now(UTC):
        raise AuthError("Token inválido ou expirado", 400)
    user.password_hash = hash_password(new_password)
    user.reset_token_hash = None
    user.reset_token_expires = None
    db.commit()


def set_own_password(db: Session, user_id: str, new_password: str) -> User:
    """Troca a própria senha (1º acesso ou a pedido). Limpa o flag de troca obrigatória."""
    user = db.get(User, user_id)
    if user is None:
        raise AuthError("Usuário não encontrado", 404)
    user.password_hash = hash_password(new_password)
    user.must_reset_password = False
    db.commit()
    db.refresh(user)
    return user


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
