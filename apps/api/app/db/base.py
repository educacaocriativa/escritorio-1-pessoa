"""Base declarativa e mixins compartilhados por todos os modelos."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class TenantMixin:
    """Toda tabela de NEGÓCIO herda isto. Garante a coluna tenant_id que a RLS usa.

    Tabelas globais (Tenant, plataforma) NÃO herdam este mixin.
    """

    tenant_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
