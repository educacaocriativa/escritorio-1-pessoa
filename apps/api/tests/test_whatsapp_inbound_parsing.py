"""Testes de parse_inbound — normaliza o payload de cada provider em InboundMessage (Onda 3).
Payloads de exemplo reais/realistas de cada provider."""
from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest

from app.core.whatsapp.inbound import InboundMessage, parse_epoch_seconds
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
        chat_jid="5511988887777@s.whatsapp.net", sender_phone="5511988887777",
        sender_name="Maria Cliente",
    )]


def test_evolution_parse_inbound_text_with_phone() -> None:
    messages = evolution.parse_inbound(EVOLUTION_TEXT_PAYLOAD)
    assert messages == [InboundMessage(
        wa_message_id="3EB0ABC123", from_phone="5511988887777", kind="text",
        text_body="Olá, tudo bem?", media_ref=None, push_name="Maria Cliente",
        chat_jid="5511988887777@s.whatsapp.net", sender_phone="5511988887777",
        sender_name="Maria Cliente",
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


# ── Evento de status de template (message_template_status_update) ───────────
#
# Payload conferido contra o exemplo oficial da Meta:
# developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/
#   message_template_status_update
# WABA em `entry[].id`, `message_template_id` INTEIRO, `reason: "NONE"` quando não há motivo,
# e a categoria vem como `message_template_category`.


def _evento_template(*, event="APPROVED", template_id=1689556908129832, reason="NONE",
                     waba="102290129340398", categoria="UTILITY") -> dict:
    value = {
        "event": event,
        "message_template_id": template_id,
        "message_template_name": "order_confirmation",
        "message_template_language": "pt_BR",
        "reason": reason,
    }
    if categoria is not None:
        value["message_template_category"] = categoria
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": waba,
            "time": 1751247548,
            "changes": [{"value": value, "field": "message_template_status_update"}],
        }],
    }


def test_parse_template_status_extrai_aprovacao() -> None:
    eventos = meta.parse_template_status(_evento_template())
    assert len(eventos) == 1
    # A Meta manda INTEIRO no webhook; `WhatsappTemplate.meta_template_id` é String(64).
    assert eventos[0].meta_template_id == "1689556908129832"
    assert eventos[0].status == "APPROVED"
    assert eventos[0].rejected_reason is None  # "NONE" da Meta NÃO é um motivo
    assert eventos[0].category == "UTILITY"


def test_parse_template_status_guarda_o_motivo_da_rejeicao() -> None:
    eventos = meta.parse_template_status(
        _evento_template(event="REJECTED", reason="INVALID_FORMAT")
    )
    assert eventos[0].status == "REJECTED"
    assert eventos[0].rejected_reason == "INVALID_FORMAT"


def test_parse_template_status_sem_categoria_devolve_none() -> None:
    """Categoria ausente não pode virar string vazia: `None` é o sinal de "não mexa no que já
    estava lá" para quem grava (ver `apply_status_events`)."""
    eventos = meta.parse_template_status(_evento_template(categoria=None))
    assert eventos[0].category is None


def test_parse_template_status_ignora_evento_de_mensagem() -> None:
    """O MESMO endpoint recebe os dois tipos. Confundi-los seria pior que ignorá-los."""
    payload = {
        "entry": [{
            "id": "102290129340398",
            "changes": [{
                "field": "messages",
                "value": {
                    "metadata": {"phone_number_id": "phone-1"},
                    "messages": [{"from": "5511900000000", "id": "wamid.1", "type": "text",
                                  "text": {"body": "oi"}}],
                },
            }],
        }],
    }
    assert meta.parse_template_status(payload) == []


def test_parse_template_status_nao_levanta_com_payload_deformado() -> None:
    """Contrato explícito: quem responde 400 é o caminho de mensagem, e há teste pra cada
    forma quebrada lá. Este parser roda ANTES e não pode roubar aquela resposta."""
    for deformado in [
        {"entry": "nao-e-lista"},
        {"entry": [{"changes": "nao-e-lista"}]},
        {"entry": [{"changes": [{"field": "message_template_status_update", "value": "boom"}]}]},
        {"entry": [{"changes": [{"value": {"event": "APPROVED"}}]}]},  # sem `field`
        {},
    ]:
        assert meta.parse_template_status(deformado) == []


def test_parse_template_status_descarta_evento_sem_id_de_template() -> None:
    payload = _evento_template()
    del payload["entry"][0]["changes"][0]["value"]["message_template_id"]
    assert meta.parse_template_status(payload) == []


def test_parse_template_status_aceita_status_que_o_produto_nao_conhece() -> None:
    """A Meta tem 14 valores de `event` (ARCHIVED, FLAGGED, LOCKED, ...) e este produto sabe
    representar 5. Filtrar é decisão de DOMÍNIO (`apply_status_events`), não do parser: aqui
    o evento passa cru, para que a decisão more num lugar só."""
    eventos = meta.parse_template_status(_evento_template(event="FLAGGED"))
    assert eventos[0].status == "FLAGGED"


def test_extract_waba_id_le_o_id_do_entry() -> None:
    assert meta.extract_waba_id(_evento_template(waba="waba-42")) == "waba-42"


def test_extract_waba_id_devolve_none_quando_nao_ha() -> None:
    assert meta.extract_waba_id({"entry": [{}]}) is None
    assert meta.extract_waba_id({"entry": "nao-e-lista"}) is None
    assert meta.extract_waba_id({"entry": [{"id": 123}]}) is None  # número não é WABA válido


# ── `occurred_at` — o instante REAL da mensagem, não o instante em que a processamos ────────
# (a dívida registrada em CLAUDE.md: sem isto, `facts.record` sempre caía no `now()`, e uma
# mensagem recebida 23h59 entrava no briefing do dia seguinte).


def test_parse_epoch_seconds_aceita_int_e_str() -> None:
    esperado = datetime(2025, 8, 5, 13, 20, 0, tzinfo=UTC)  # 1754400000
    assert parse_epoch_seconds(1754400000) == esperado
    assert parse_epoch_seconds("1754400000") == esperado


def test_parse_epoch_seconds_devolve_none_para_valor_ausente_ou_ilegivel() -> None:
    assert parse_epoch_seconds(None) is None
    assert parse_epoch_seconds("") is None
    assert parse_epoch_seconds("não-é-número") is None


def test_evolution_parse_inbound_le_o_messageTimestamp() -> None:
    payload = {
        "data": {
            "key": {"id": "3EB0TS1", "remoteJid": "5511988887777@s.whatsapp.net"},
            "pushName": "Maria Cliente",
            "message": {"conversation": "oi"},
            "messageTimestamp": 1754400000,
        }
    }
    msg = evolution.parse_inbound(payload)[0]
    assert msg.occurred_at == datetime(2025, 8, 5, 13, 20, 0, tzinfo=UTC)


def test_evolution_parse_inbound_sem_messageTimestamp_devolve_none() -> None:
    # EVOLUTION_TEXT_PAYLOAD (acima) não tem messageTimestamp — o caso comum de payload
    # deliberadamente incompleto: occurred_at fica None, e quem grava o fato cai no `now()`.
    assert evolution.parse_inbound(EVOLUTION_TEXT_PAYLOAD)[0].occurred_at is None


def test_meta_parse_inbound_le_o_timestamp_da_mensagem() -> None:
    payload = {
        "entry": [{"changes": [{"value": {
            "contacts": [{"profile": {"name": "Maria"}}],
            "messages": [{
                "id": "wamid.TS1", "from": "5511988887777", "type": "text",
                "text": {"body": "oi"}, "timestamp": "1754400000",
            }],
        }}]}]
    }
    msg = meta.parse_inbound(payload)[0]
    assert msg.occurred_at == datetime(2025, 8, 5, 13, 20, 0, tzinfo=UTC)


def test_meta_parse_inbound_sem_timestamp_devolve_none() -> None:
    assert meta.parse_inbound(META_TEXT_PAYLOAD)[0].occurred_at is None
