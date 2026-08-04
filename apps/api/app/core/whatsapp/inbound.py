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
    media_ref: str | None  # referência de mídia OPACA que exige um fetch depois (meta_media_id
    # da Meta — resolvida pelo worker via `fetch_media_url`/`download_media`). A Evolution não
    # entrega media_ref: ela entrega os BYTES já decodificados abaixo (media_bytes), porque não
    # tem endpoint de resolução separado (ver `providers/evolution.py::fetch_media_url`).
    push_name: str
    from_me: bool = False  # a mensagem foi ESCRITA PELO DONO, não pelo contato — vira
    # `direction="out"` no ingest. Só a Evolution produz isto: o Baileys espelha no webhook
    # tudo que acontece no aparelho, inclusive o que o dono digitou no WhatsApp do celular
    # (`key.fromMe=true`). A Meta nunca entrega mensagem própria no array `messages` do
    # webhook (só status de entrega, em `statuses`), então o provider Meta deixa no default.
    media_bytes: bytes | None = None  # mídia JÁ decodificada (Evolution, quando webhookBase64
    # está ligado) — ingest cria o Attachment na hora, sem depender do worker.
    media_mime_type: str | None = None
    media_filename: str | None = None
