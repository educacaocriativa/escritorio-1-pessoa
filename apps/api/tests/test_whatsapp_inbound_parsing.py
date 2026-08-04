"""Testes de parse_inbound — normaliza o payload de cada provider em InboundMessage (Onda 3).
Payloads de exemplo reais/realistas de cada provider."""
from __future__ import annotations

import base64

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


def test_evolution_parse_inbound_marks_from_me() -> None:
    """`key.fromMe=true` = o DONO escreveu (no WhatsApp do celular dele) e o Baileys espelhou
    no mesmo evento `messages.upsert`. Sem ler este campo, as duas pontas da conversa entram
    como recebidas e a tela de Conversas fica sem autor."""
    payload = {
        "data": {
            "key": {
                "id": "3EB0MINE", "remoteJid": "5511988887777@s.whatsapp.net", "fromMe": True,
            },
            "pushName": "Nome Do Dono",
            "message": {"conversation": "Ok, fechado"},
        }
    }
    msg = evolution.parse_inbound(payload)[0]
    assert msg.from_me is True
    # O remoteJid de uma mensagem PRÓPRIA é o do destinatário — o contato continua resolvido
    # corretamente; só a autoria muda.
    assert msg.from_phone == "5511988887777"


def test_evolution_parse_inbound_from_me_default_is_false() -> None:
    assert evolution.parse_inbound(EVOLUTION_TEXT_PAYLOAD)[0].from_me is False


def test_evolution_parse_inbound_media_carries_from_me() -> None:
    payload = {
        "data": {
            "key": {"id": "3EB0IMGME", "remoteJid": "5511988887777@s.whatsapp.net",
                    "fromMe": True},
            "pushName": "Nome Do Dono",
            "message": {
                "imageMessage": {"mimetype": "image/jpeg", "caption": "segue o print"},
                "base64": base64.b64encode(b"fake").decode(),
            },
        }
    }
    msg = evolution.parse_inbound(payload)[0]
    assert msg.from_me is True
    assert msg.kind == "image"


def test_meta_parse_inbound_never_marks_from_me() -> None:
    """O webhook da Meta não entrega mensagem própria no array `messages` (só status de entrega,
    em `statuses`) — o provider Meta deixa `from_me` no default."""
    assert meta.parse_inbound(META_TEXT_PAYLOAD)[0].from_me is False


def test_evolution_parse_inbound_malformed_payload_returns_empty() -> None:
    assert evolution.parse_inbound({"unexpected": "shape"}) == []
    assert evolution.parse_inbound({}) == []


# --- Evolution: mídia (imagem/áudio/documento) — shape real confirmado ao vivo contra a v2.3.7
# (payload de produção capturado 2026-08-04: imageMessage com url/mimetype/caption direto no
# objeto, e message.base64 como irmão de imageMessage quando webhookBase64 está ligado — ver
# whatsapp.baileys.service.ts, messageRaw.message.base64 = buffer.toString('base64')) ------------

def test_evolution_parse_inbound_image_with_base64() -> None:
    payload = {
        "data": {
            "key": {"id": "3EB0IMG1", "remoteJid": "5511988887777@s.whatsapp.net"},
            "pushName": "Maria Cliente",
            "message": {
                "imageMessage": {
                    "url": "https://mmg.whatsapp.net/o1/v/t24/...",
                    "mimetype": "image/jpeg",
                    "caption": "olha essa foto",
                },
                "base64": base64.b64encode(b"fake-jpeg-bytes").decode(),
            },
        }
    }
    messages = evolution.parse_inbound(payload)
    assert len(messages) == 1
    msg = messages[0]
    assert msg.kind == "image"
    assert msg.from_phone == "5511988887777"
    assert msg.text_body == "olha essa foto"
    assert msg.media_bytes == b"fake-jpeg-bytes"
    assert msg.media_mime_type == "image/jpeg"


def test_evolution_parse_inbound_image_without_base64_has_no_bytes() -> None:
    # Evolution não conseguiu baixar (erro dela) ou webhookBase64 desligado — a mensagem ainda é
    # registrada (com legenda), só sem os bytes.
    payload = {
        "data": {
            "key": {"id": "3EB0IMG2", "remoteJid": "5511988887777@s.whatsapp.net"},
            "pushName": "Maria Cliente",
            "message": {"imageMessage": {"mimetype": "image/jpeg", "caption": "sem bytes"}},
        }
    }
    messages = evolution.parse_inbound(payload)
    assert messages[0].kind == "image"
    assert messages[0].media_bytes is None
    assert messages[0].text_body == "sem bytes"


def test_evolution_parse_inbound_document_with_caption_wrapper() -> None:
    # Documento com legenda vem embrulhado em documentWithCaptionMessage.message.documentMessage
    # (um nível a mais que um documento simples).
    payload = {
        "data": {
            "key": {"id": "3EB0DOC1", "remoteJid": "5511988887777@s.whatsapp.net"},
            "pushName": "Maria Cliente",
            "message": {
                "documentWithCaptionMessage": {
                    "message": {
                        "documentMessage": {
                            "mimetype": "text/markdown",
                            "fileName": "learnings.md",
                            "caption": "segue o arquivo",
                        }
                    }
                },
                "base64": base64.b64encode(b"# markdown").decode(),
            },
        }
    }
    messages = evolution.parse_inbound(payload)
    msg = messages[0]
    assert msg.kind == "document"
    assert msg.media_filename == "learnings.md"
    assert msg.text_body == "segue o arquivo"
    assert msg.media_bytes == b"# markdown"


def test_evolution_parse_inbound_audio_strips_codec_suffix_from_mimetype() -> None:
    payload = {
        "data": {
            "key": {"id": "3EB0AUD1", "remoteJid": "5511988887777@s.whatsapp.net"},
            "pushName": "Maria Cliente",
            "message": {
                "audioMessage": {"mimetype": "audio/ogg; codecs=opus"},
                "base64": base64.b64encode(b"fake-audio").decode(),
            },
        }
    }
    messages = evolution.parse_inbound(payload)
    assert messages[0].kind == "audio"
    assert messages[0].media_mime_type == "audio/ogg"
    assert messages[0].text_body == ""


def test_evolution_parse_inbound_invalid_base64_returns_empty() -> None:
    payload = {
        "data": {
            "key": {"id": "3EB0BAD1", "remoteJid": "5511988887777@s.whatsapp.net"},
            "pushName": "Maria Cliente",
            "message": {
                "imageMessage": {"mimetype": "image/jpeg", "caption": ""},
                "base64": "not-valid-base64!!!",
            },
        }
    }
    assert evolution.parse_inbound(payload) == []


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
