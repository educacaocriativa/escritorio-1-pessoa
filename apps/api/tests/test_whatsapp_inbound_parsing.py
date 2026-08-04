"""Testes de parse_inbound — normaliza o payload de cada provider em InboundMessage (Onda 3).
Payloads de exemplo reais/realistas de cada provider."""
from __future__ import annotations

from app.core.whatsapp.inbound import InboundMessage
from app.core.whatsapp.providers import evolution, meta

META_TEXT_PAYLOAD = {
    "entry": [{
        "changes": [{
            "value": {
                "contacts": [{"profile": {"name": "Maria Cliente"}}],
                "messages": [{
                    "id": "wamid.123", "from": "5511988887777", "type": "text",
                    "text": {"body": "Olá, tudo bem?"},
                }],
            }
        }]
    }]
}

EVOLUTION_TEXT_PAYLOAD = {
    "data": {
        "key": {"id": "3EB0ABC123", "remoteJid": "5511988887777@s.whatsapp.net"},
        "pushName": "Maria Cliente",
        "message": {"conversation": "Olá, tudo bem?"},
    }
}

EVOLUTION_LID_PAYLOAD = {
    "data": {
        "key": {"id": "3EB0DEF456", "remoteJid": "123456789@lid"},
        "pushName": "Cliente Sem Numero",
        "message": {"conversation": "Oi"},
    }
}


def test_meta_parse_inbound_text() -> None:
    messages = meta.parse_inbound(META_TEXT_PAYLOAD)
    assert messages == [InboundMessage(
        wa_message_id="wamid.123", from_phone="5511988887777", kind="text",
        text_body="Olá, tudo bem?", media_ref=None, push_name="Maria Cliente",
    )]


def test_evolution_parse_inbound_text_with_phone() -> None:
    messages = evolution.parse_inbound(EVOLUTION_TEXT_PAYLOAD)
    assert messages == [InboundMessage(
        wa_message_id="3EB0ABC123", from_phone="5511988887777", kind="text",
        text_body="Olá, tudo bem?", media_ref=None, push_name="Maria Cliente",
    )]


def test_evolution_parse_inbound_lid_has_no_phone() -> None:
    """@lid esconde o telefone — from_phone=None, NUNCA adivinhado (ver Task 9, bandeja
    "Não identificados")."""
    messages = evolution.parse_inbound(EVOLUTION_LID_PAYLOAD)
    assert messages[0].from_phone is None
    assert messages[0].wa_message_id == "3EB0DEF456"
    assert messages[0].push_name == "Cliente Sem Numero"


def test_evolution_parse_inbound_malformed_payload_returns_empty() -> None:
    assert evolution.parse_inbound({"unexpected": "shape"}) == []
    assert evolution.parse_inbound({}) == []
