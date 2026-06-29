"""Regras do Super Admin: gestão de contas (tenant + owner) por todo o sistema.

As tabelas `tenants`/`users` são GLOBAIS (sem RLS) — o Master as consulta diretamente.
Para EXCLUIR uma conta, purgamos os dados de negócio (com RLS, por tenant) e depois removemos
as linhas globais.
"""
from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.base import TenantMixin
from app.db.registry import Base  # importa todos os modelos -> registra as tabelas
from app.db.session import tenant_session
from app.modules.auth.models import Tenant, User
from app.modules.auth.schemas import RegisterRequest
from app.modules.auth.service import register_tenant
from app.modules.platform.schemas import UpdateAccountRequest


def _business_table_names() -> set[str]:
    """Tabelas de NEGÓCIO (subclasses de TenantMixin), descobertas dinamicamente.

    Assim, qualquer módulo futuro com dados por tenant é purgado automaticamente na exclusão
    de conta — sem precisar lembrar de editar uma lista hardcoded.
    """
    return {
        mapper.class_.__tablename__
        for mapper in Base.registry.mappers
        if issubclass(mapper.class_, TenantMixin)
    }


def _has_platform_admin(db: Session, tenant_id: str) -> bool:
    return (
        db.scalar(
            select(User.id).where(
                User.tenant_id == tenant_id, User.is_platform_admin.is_(True)
            )
        )
        is not None
    )


class PlatformError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _owner_of(db: Session, tenant_id: str) -> User | None:
    return db.scalar(
        select(User).where(User.tenant_id == tenant_id, User.role == "owner")
    )


def list_accounts(db: Session) -> list[tuple[Tenant, User | None]]:
    """Todas as contas reais (exclui o tenant interno da plataforma)."""
    tenants = list(db.scalars(select(Tenant).order_by(Tenant.created_at.desc())).all())
    out: list[tuple[Tenant, User | None]] = []
    for t in tenants:
        owner = _owner_of(db, t.id)
        # pula contas de plataforma (admins)
        if owner and owner.is_platform_admin:
            continue
        out.append((t, owner))
    return out


def create_account(db: Session, data: RegisterRequest) -> tuple[Tenant, User]:
    return register_tenant(db, data)


def get_user(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise PlatformError("Usuário não encontrado", 404)
    return user


def update_account(db: Session, user_id: str, data: UpdateAccountRequest) -> User:
    user = get_user(db, user_id)
    if user.is_platform_admin:
        raise PlatformError("Não é possível editar o administrador da plataforma por aqui", 400)
    if data.name is not None:
        user.name = data.name
    if data.is_active is not None:
        user.is_active = data.is_active
    db.commit()
    db.refresh(user)
    return user


def delete_account(db: Session, tenant_id: str) -> None:
    """Exclui a conta de forma ATÔMICA: purga dados de negócio + remove tenant e usuários,
    tudo numa única transação. Bloqueia se houver qualquer administrador no tenant.
    """
    if db.get(Tenant, tenant_id) is None:
        raise PlatformError("Conta não encontrada", 404)
    if _has_platform_admin(db, tenant_id):
        raise PlatformError("Não é possível excluir uma conta de administrador", 400)

    biz = _business_table_names()
    # Uma só transação (tenant_session commita ao sair) => sem estado órfão em falha parcial.
    # Os nomes de tabela vêm do nosso metadata (não de input), então o DELETE é seguro.
    # WHERE tenant_id explícito = defesa-em-profundidade nesta operação destrutiva (além da RLS).
    with tenant_session(tenant_id) as tdb:
        for table in reversed(Base.metadata.sorted_tables):  # ordem FK-segura p/ delete
            if table.name in biz:
                # table.name vem do nosso metadata (não de input) e está em `biz` — seguro.
                tdb.execute(
                    text(f"DELETE FROM {table.name} WHERE tenant_id = :tid"),  # noqa: S608
                    {"tid": tenant_id},
                )
        tdb.execute(text("DELETE FROM users WHERE tenant_id = :tid"), {"tid": tenant_id})
        tdb.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
