"""Testes de parse_inbound — normaliza o payload de cada provider em InboundMessage (Onda 3).
Payloads de exemplo reais/realistas de cada provider."""
from __future__ import annotations

import pytest

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


# --- Meta: shape do LOTE quebrado levanta ValueError (movido de test_whatsapp_inbox_service.py,
# que testava isso indiretamente via ingest_webhook_payload antes da Onda 3) -------------------

def test_meta_parse_inbound_raises_on_non_dict_value() -> None:
    # `change["value"]` não é dict — shape do lote inteiro quebrado, não uma mensagem específica.
    payload = {"entry": [{"changes": [{"value": "boom"}]}]}
    with pytest.raises(ValueError, match="value"):
        meta.parse_inbound(payload)


def test_meta_parse_inbound_raises_when_messages_is_not_a_list_of_dicts() -> None:
    # `value["messages"]` é uma string — iterar produziria caracteres individuais, não mensagens.
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "contacts": [{"profile": {"name": "Fulano"}}],
                    "messages": "not-a-list",
                },
            }],
        }],
    }
    with pytest.raises(ValueError, match="messages"):
        meta.parse_inbound(payload)


def test_meta_parse_inbound_skips_only_the_malformed_message_text_field() -> None:
    # `text` de UMA mensagem é uma string, não um dict — isola só essa mensagem; não levanta,
    # não derruba as demais do mesmo lote.
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "contacts": [{"profile": {"name": "Fulano"}}],
                    "messages": [
                        {"id": "w1", "from": "5511900000001", "type": "text", "text": "not-a-dict"},
                        {"id": "w2", "from": "5511900000002", "type": "text",
                         "text": {"body": "oi"}},
                    ],
                },
            }],
        }],
    }
    messages = meta.parse_inbound(payload)
    assert len(messages) == 1
    assert messages[0].wa_message_id == "w2"


def test_meta_parse_inbound_skips_only_the_malformed_media_field() -> None:
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "contacts": [{"profile": {"name": "Fulano"}}],
                    "messages": [
                        {"id": "w1", "from": "5511900000001", "type": "image",
                         "image": "not-a-dict"},
                    ],
                },
            }],
        }],
    }
    assert meta.parse_inbound(payload) == []
