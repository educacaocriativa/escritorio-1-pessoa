"""Conversa de WhatsApp (inbox): mensagens trocadas com o cliente (RLS) + resolução
pré-autenticação do webhook (tabela global, sem RLS).

Não confundir com `whatsapp_templates` (templates aprovados pela Meta) — aqui é a conversa de
verdade, ida-e-volta, entre o tenant e o cliente. Ver docs/superpowers/specs/
2026-07-19-whatsapp-inbox-design.md.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

DIRECTION_IN = "in"
DIRECTION_OUT = "out"
DIRECTIONS = (DIRECTION_IN, DIRECTION_OUT)

KIND_TEXT = "text"
KIND_IMAGE = "image"
KIND_AUDIO = "audio"
KIND_DOCUMENT = "document"
KIND_VIDEO = "video"
KINDS = (KIND_TEXT, KIND_IMAGE, KIND_AUDIO, KIND_DOCUMENT, KIND_VIDEO)

MEDIA_STATUS_NONE = "none"
MEDIA_STATUS_PENDING = "pending"
MEDIA_STATUS_DOWNLOADED = "downloaded"
MEDIA_STATUS_FAILED = "failed"


class WhatsappMessage(Base, TenantMixin, TimestampMixin):
    __tablename__ = "whatsapp_messages"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "wa_message_id", name="uq_whatsapp_messages_tenant_wa_id"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    client_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    direction: Mapped[str] = mapped_column(String(4), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default=KIND_TEXT, nullable=False)
    text_body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Link pro módulo de Anexos já existente (reaproveita storage S3/Postgres).
    media_attachment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Só relevante pra mídia `in` (baixada de forma assíncrona pelo worker).
    media_status: Mapped[str] = mapped_column(
        String(16), default=MEDIA_STATUS_NONE, nullable=False
    )
    # ID da própria Meta — evita duplicar se o webhook reentregar a mesma mensagem.
    wa_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # ID de mídia da Meta (distinto de wa_message_id, que é o ID da MENSAGEM) — só setado
    # quando kind != "text" e ainda não baixamos os bytes.
    meta_media_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Só relevante pra `direction=out` ("sent"|"logged"|"failed", mesmo vocabulário de sempre).
    status: Mapped[str] = mapped_column(String(16), default="sent", nullable=False)


class WhatsappConversationState(Base, TenantMixin, TimestampMixin):
    """Uma linha por cliente com atividade — só guarda `last_read_at` (compartilhado entre toda
    a equipe do tenant: "lida por qualquer um" marca lida pra todos, sem granularidade por
    atendente, mesma decisão de 'inbox compartilhada' do brainstorming)."""

    __tablename__ = "whatsapp_conversation_states"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "client_id", name="uq_whatsapp_conv_state_tenant_client"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    client_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PublicWhatsappAccount(Base, TimestampMixin):
    """Snapshot GLOBAL (sem RLS, SEM TenantMixin) — resolve `tenant_id` a partir do
    `phone_number_id` ANTES de qualquer autenticação. O webhook da Meta não manda tenant nenhum,
    só o `phone_number_id` que recebeu a mensagem; esta tabela é o único jeito de saber de quem é
    o evento e qual `app_secret` usar pra validar a assinatura. Mesmo padrão de
    `PublicIntegrationKey`/`published_pages`. Mantida em sincronia (dual-write) por
    `settings/service.py::update_profile` toda vez que o tenant salva/altera as credenciais.
    """

    __tablename__ = "public_whatsapp_accounts"

    phone_number_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    app_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    verify_token: Mapped[str] = mapped_column(String(64), nullable=False)
