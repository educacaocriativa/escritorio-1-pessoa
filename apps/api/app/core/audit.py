"""Trilha de auditoria (Regra de Ouro nº 3).

Toda ação relevante grava quem fez. Ações da IA marcam is_ai=True, que a UI mostra como
"Ação executada pela IA".
"""
from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid


class AuditEntry(Base, TenantMixin, TimestampMixin):
    __tablename__ = "audit_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)  # user_id ou "ai"
    is_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target: Mapped[str] = mapped_column(String(255), default="", nullable=False)


def record(db, *, tenant_id: str, actor: str, action: str, target: str = "", is_ai: bool = False):
    """Grava uma entrada de auditoria. Chame em toda mutação de dados de negócio."""
    entry = AuditEntry(
        tenant_id=tenant_id, actor=actor, action=action, target=target, is_ai=is_ai
    )
    db.add(entry)
    return entry


class PlatformAuditEntry(Base, TimestampMixin):
    """Log de PLATAFORMA (fora do tenant) para operações destrutivas do Master (LGPD).

    Deliberadamente SEM ``TenantMixin``: assim `_business_table_names()` (descoberta dinâmica
    via ``issubclass(mapper.class_, TenantMixin)`` em platform/service.py) NUNCA a inclui na
    purga por tenant. Por isso o registro SOBREVIVE à exclusão da conta — resta o rastro de
    quem/quando/qual tenant, que os `audit_entries` do próprio tenant (esses sim, purgados)
    não conseguem preservar.

    Guarda SNAPSHOTS (``actor_email``, ``target_tenant_slug``) porque o tenant-alvo é apagado
    logo em seguida: não há como fazer FK/join depois. O ator é sempre o Master (não é apagado),
    mas mantemos o e-mail como snapshot para o log ser autossuficiente.
    """

    __tablename__ = "platform_audit_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    actor_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_email: Mapped[str] = mapped_column(String(255), nullable=False)
    target_tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    target_tenant_slug: Mapped[str] = mapped_column(String(63), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)


def record_platform(
    db,
    *,
    actor_user_id: str,
    actor_email: str,
    target_tenant_id: str,
    target_tenant_slug: str,
    action: str,
):
    """Grava um log de PLATAFORMA (fora do tenant), que sobrevive à purga do tenant.

    Use para operações destrutivas do Master (ex.: exclusão de conta), gravando na sessão
    GLOBAL (`get_db`), NUNCA numa `tenant_session` do tenant que está sendo apagado.
    """
    entry = PlatformAuditEntry(
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        target_tenant_id=target_tenant_id,
        target_tenant_slug=target_tenant_slug,
        action=action,
    )
    db.add(entry)
    return entry
