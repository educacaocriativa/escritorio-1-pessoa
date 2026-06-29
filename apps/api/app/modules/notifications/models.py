"""Registro de notificações enviadas (WhatsApp/e-mail). Tabela de NEGÓCIO (RLS)."""
from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid


class Notification(Base, TenantMixin, TimestampMixin):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    channel: Mapped[str] = mapped_column(String(16), default="whatsapp", nullable=False)
    recipient: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    # Cliente destinatário (p/ histórico). Notificações internas ao owner ficam com None.
    client_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # sent (entregue), logged (sem provedor ainda), failed
    status: Mapped[str] = mapped_column(String(16), default="logged", nullable=False)
