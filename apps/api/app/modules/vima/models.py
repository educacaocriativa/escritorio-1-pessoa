"""O briefing gravado. Idempotente por (tenant, usuário, dia de referência)."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid


class Briefing(Base, TenantMixin, TimestampMixin):
    __tablename__ = "briefings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "reference_date", name="uq_briefing_dia"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    reference_date: Mapped[date] = mapped_column(Date, nullable=False)
    # O payload composto, guardado como evidência do que a IA recebeu. Sem ele não dá para
    # auditar uma narração estranha.
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    texto: Mapped[str] = mapped_column(Text, nullable=False)
    por_ia: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    vazio: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
