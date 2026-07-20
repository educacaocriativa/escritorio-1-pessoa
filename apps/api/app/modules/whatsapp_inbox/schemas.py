# apps/api/app/modules/whatsapp_inbox/schemas.py
"""Schemas do inbox de WhatsApp: lista de conversas, linha do tempo, resposta."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ConversationSummary(BaseModel):
    client_id: str
    client_name: str
    client_phone: str | None
    last_message_at: datetime | None
    last_message_preview: str
    unread: bool


class TimelineEntry(BaseModel):
    source: str  # "conversation" | "automated"
    direction: str  # "in" | "out"
    kind: str
    text_body: str
    media_attachment_id: str | None
    purpose_label: str | None
    created_at: datetime


class SendTextRequest(BaseModel):
    text: str


class SendTemplateRequest(BaseModel):
    template_id: str
    variables: list[str] = []
