"""Testes da bandeja "Não identificados" — mensagens sem client_id resolvido (Onda 3, ver
docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md §6)."""
from __future__ import annotations

from app.modules.whatsapp_inbox import service
from app.modules.whatsapp_inbox.models import DIRECTION_IN, WhatsappMessage

TENANT_ID = "55555555-5555-5555-5555-555555555555"


def test_list_conversations_includes_unidentified_bucket_when_present(db) -> None:
    db.add(WhatsappMessage(
        tenant_id=TENANT_ID, client_id=None, direction=DIRECTION_IN, kind="text",
        text_body="oi, sou eu", wa_message_id="wa-1",
    ))
    db.commit()
    conversations = service.list_conversations(db, TENANT_ID)
    unidentified = [c for c in conversations if c["client_id"] is None]
    assert len(unidentified) == 1
    assert unidentified[0]["client_name"] == "Não identificados"


def test_list_conversations_omits_unidentified_bucket_when_absent(db) -> None:
    conversations = service.list_conversations(db, TENANT_ID)
    assert all(c["client_id"] is not None for c in conversations)
