"""Modelos de identidade: Tenant (global) e User.

Tenant é uma tabela GLOBAL (sem tenant_id / sem RLS) — representa a "empresa de 1 pessoa".
User pertence a um Tenant. O login é por e-mail (único globalmente), pois cada owner é uma
identidade única na plataforma. Sub-usuários (contador, estagiário) herdam o tenant do owner.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, _uuid


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(63), unique=True, index=True, nullable=False)
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    document: Mapped[str] = mapped_column(String(18), nullable=False)  # CPF/CNPJ

    users: Mapped[list[User]] = relationship(back_populates="tenant")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="owner", nullable=False)
    # RBAC: módulos liberados p/ sub-usuário. Vazio = todos (owner).
    allowed_modules: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Nível 1 (Master/plataforma): gerencia todas as contas. NÃO é o owner de um tenant comum.
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Cadastro completo (usado no convite de novos usuários).
    document: Mapped[str | None] = mapped_column(String(18), nullable=True)  # CPF
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)  # WhatsApp
    # True quando a senha foi gerada pela plataforma e o usuário deve trocá-la no 1º acesso.
    must_reset_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Recuperação de senha: guardamos o HASH (sha256) do token, nunca o token cru.
    reset_token_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    reset_token_expires: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tenant: Mapped[Tenant] = relationship(back_populates="users")
