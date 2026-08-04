"""Formato normalizado de mensagem recebida — o que sobra depois que cada provider (Meta,
Evolution) traduz o próprio formato de payload. De `whatsapp_inbox/service.py` pra dentro
(resolver cliente, criar lead, deduplicar, enfileirar mídia pendente) nada sabe qual provider
originou a mensagem — só enxerga isto. Ver
docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md §6.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InboundMessage:
    wa_message_id: str
    from_phone: str | None  # só dígitos, sem "+". None quando o provider não entrega o número
    kind: str  # text | image | audio | document | video
    text_body: str
    media_ref: str | None  # referência de mídia opaca (meta_media_id, ou base64 da Evolution)
    push_name: str
