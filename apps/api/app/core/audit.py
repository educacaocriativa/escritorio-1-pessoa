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
