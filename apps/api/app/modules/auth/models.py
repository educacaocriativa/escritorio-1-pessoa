"""Modelos de identidade: Tenant (global) e User.

Tenant é uma tabela GLOBAL (sem tenant_id / sem RLS) — representa a "empresa de 1 pessoa".
User pertence a um Tenant. O login é por e-mail (único globalmente), pois cada owner é uma
identidade única na plataforma. Sub-usuários (contador, estagiário) herdam o tenant do owner.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.tz import DEFAULT_TENANT_TIMEZONE
from app.db.base import Base, TimestampMixin, _uuid


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(63), unique=True, index=True, nullable=False)
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    document: Mapped[str] = mapped_column(String(18), nullable=False)  # CPF/CNPJ
    # Fuso IANA do tenant — a âncora de "hoje" de todo o sistema (`settings.hoje_do_tenant`).
    #
    # Mora AQUI, e não em `TenantProfile`, porque `/auth/login` e `/auth/me` entregam o fuso junto
    # com a sessão e rodam em sessão crua: `tenant_profiles` tem RLS FORCE e a leitura voltava
    # vazia, caindo no padrão em silêncio para todo tenant. Fuso é identidade, não brand kit.
    # Ver a migration 0073 e `tests/test_auth_timezone_rls.py`.
    timezone: Mapped[str] = mapped_column(
        String(64), default=DEFAULT_TENANT_TIMEZONE, nullable=False
    )

    users: Mapped[list[User]] = relationship(back_populates="tenant")


class User(Base, TimestampMixin):
    __tablename__ = "users"
    # Documento (CPF/CNPJ) único DENTRO do tenant — nunca global: `users` é tabela sem RLS e
    # tenants distintos podem legitimamente ter o mesmo documento. NULLs são distintos (owner
    # via /register e o admin de plataforma têm document=None, então não colidem entre si).
    __table_args__ = (
        UniqueConstraint("tenant_id", "document", name="uq_user_tenant_document"),
    )

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

    # Briefing da Vima (Onda 4) — preferência DO USUÁRIO, não da empresa. Mora aqui, e não em
    # `TenantProfile`, porque dois usuários do mesmo tenant têm horários e telefones diferentes;
    # no perfil da empresa um sobrescreveria o outro. Também é o que permite editá-la sem o
    # módulo `settings` (ver `auth/router.py::preferences`).
    briefing_whatsapp_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    # "HH:MM" no relógio de parede do dono — comparada com a hora LOCAL do tenant pelo scheduler,
    # nunca com UTC. Ver a migration 0072 para o porquê de ser texto e não `Time`.
    briefing_hour: Mapped[str] = mapped_column(String(5), default="07:00", nullable=False)

    # Recuperação de senha: guardamos o HASH (sha256) do token, nunca o token cru.
    reset_token_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    reset_token_expires: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tenant: Mapped[Tenant] = relationship(back_populates="users")
