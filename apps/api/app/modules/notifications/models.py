"""Registro de notificações enviadas (WhatsApp/e-mail). Tabela de NEGÓCIO (RLS).

Também é a FILA de envios assíncronos (Story 4.3): uma notificação criada com
`status="pending"` é enfileirada (via `service.enqueue`) e só é entregue depois pelo worker
(`service.process_pending`), fora do request/response HTTP. Os valores possíveis de `status`:
- ``pending``: enfileirada, ainda não processada pelo worker.
- ``sent``: entregue de verdade pelo provedor.
- ``logged``: sem provedor configurado (stub) — registrada, não entregue.
- ``failed``: a tentativa de envio lançou; ``last_error`` guarda o motivo.
"""
from __future__ import annotations

from sqlalchemy import JSON, Integer, String, Text
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
    # pending (enfileirada), sent (entregue), logged (sem provedor ainda), failed
    status: Mapped[str] = mapped_column(String(16), default="logged", nullable=False)
    # Fila assíncrona (Story 4.3): nº de tentativas de envio e último erro (se falhou).
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    # Template WhatsApp resolvido no ENFILEIRAMENTO (dentro da request) — o worker entrega
    # depois (process_pending) sem precisar recalcular propósito/vínculo. NULL nas 3 = mesmo
    # comportamento antigo (texto livre em `message`, via send_text).
    whatsapp_template_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    whatsapp_template_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    whatsapp_template_variables: Mapped[list | None] = mapped_column(JSON, nullable=True)
