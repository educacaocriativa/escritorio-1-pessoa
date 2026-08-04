# apps/api/tests/test_whatsapp_inbox_service.py
"""Testes do serviço do inbox de WhatsApp: ingestão do webhook, lead automático, timeline
unificada, janela de 24h, resposta (texto/mídia/template)."""
import pytest
from sqlalchemy import select

from app.core import whatsapp
from app.core.audit import AuditEntry
from app.core.whatsapp.inbound import InboundMessage
from app.core.whatsapp.providers import meta
from app.modules.attachments.models import Attachment
from app.modules.crm.models import Client
from app.modules.notifications.models import Notification
from app.modules.settings import service as settings_service
from app.modules.settings.models import TenantProfile
from app.modules.whatsapp_inbox import service as inbox_service
from app.modules.whatsapp_inbox.models import (
    DIRECTION_IN,
    DIRECTION_OUT,
    MEDIA_STATUS_DOWNLOADED,
    MEDIA_STATUS_FAILED,
    MEDIA_STATUS_PENDING,
    PublicWhatsappAccount,
    WhatsappChat,
    WhatsappMessage,
)
from app.modules.whatsapp_templates.models import WhatsappTemplate

TENANT_ID = "11111111-1111-1111-1111-111111111111"


def _configure_credentials(db) -> TenantProfile:
    profile = settings_service.get_profile(db, TENANT_ID)
    profile.whatsapp_token = "tok"
    profile.whatsapp_phone_id = "phone-123"
    profile.whatsapp_waba_id = "waba"
    profile.whatsapp_app_secret = "secret"
    profile.whatsapp_verify_token = "verify-abc"
    db.add(PublicWhatsappAccount(
        phone_number_id="phone-123", tenant_id=TENANT_ID, app_secret="secret",
        verify_token="verify-abc",
    ))
    db.commit()
    return profile


def _text_message_payload(*, phone_number_id: str, wa_id: str, from_number: str, body: str,
                           msg_id: str = "wamid.abc") -> dict:
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "metadata": {"phone_number_id": phone_number_id},
                    "contacts": [{"profile": {"name": "Fulano"}, "wa_id": wa_id}],
                    "messages": [{
                        "from": from_number, "id": msg_id, "type": "text",
                        "text": {"body": body},
                    }],
                },
                "field": "messages",
            }],
        }],
    }


def test_resolve_account_finds_by_phone_number_id(db):
    db.add(PublicWhatsappAccount(
        phone_number_id="phone-resolve-1", tenant_id=TENANT_ID, app_secret="segredo-resolve",
        verify_token="verify-resolve-1",
    ))
    db.commit()
    account = inbox_service.resolve_account(db, phone_number_id="phone-resolve-1")
    assert account is not None
    assert account.tenant_id == TENANT_ID
    assert account.app_secret == "segredo-resolve"


def test_resolve_account_returns_none_for_unknown_number(db):
    assert inbox_service.resolve_account(db, phone_number_id="numero-inexistente") is None


def test_resolve_by_verify_token_finds_by_token(db):
    db.add(PublicWhatsappAccount(
        phone_number_id="phone-resolve-2", tenant_id=TENANT_ID, app_secret="segredo-resolve-2",
        verify_token="verify-resolve-2",
    ))
    db.commit()
    account = inbox_service.resolve_by_verify_token(db, verify_token="verify-resolve-2")
    assert account is not None
    assert account.tenant_id == TENANT_ID
    assert account.phone_number_id == "phone-resolve-2"


def test_resolve_by_verify_token_returns_none_for_unknown_token(db):
    assert inbox_service.resolve_by_verify_token(db, verify_token="token-inexistente") is None


def test_resolve_account_rejects_phone_number_id_with_nul_byte(db):
    # JSON permite um NUL escapado numa string e `json.loads` produz um `str` Python com NUL de
    # verdade. No driver de produção (psycopg), fazer bind desse valor num parâmetro de query
    # levanta `psycopg.DataError` — não capturado em lugar nenhum do caminho do webhook. SQLite
    # (usado nos testes) tolera NUL em campos de texto, então este teste prova a GUARDA em si
    # (retorna None em vez de deixar o valor chegar ao `db.get`), não o crash do driver real.
    assert inbox_service.resolve_account(db, phone_number_id="pn\x00id") is None


def test_resolve_account_rejects_phone_number_id_with_lone_surrogate(db):
    # JSON permite um escape de surrogate solto (`"\uD800"`) numa string, e `json.loads` produz
    # um `str` Python de verdade contendo o surrogate — de um payload/UTF-8 perfeitamente válido.
    # Diferente do NUL (que o SQLite tolera de boa), um surrogate solto NÃO pode ser codificado
    # em UTF-8 (`'\ud800'.encode('utf-8')` levanta `UnicodeEncodeError`) e o driver `sqlite3` do
    # Python também rejeita na hora do bind — sem a guarda, esta chamada RAISES em vez de
    # retornar None (prova que a guarda discrimina de verdade, ao contrário do caso do NUL).
    assert inbox_service.resolve_account(db, phone_number_id="\ud800") is None


def test_resolve_by_verify_token_rejects_verify_token_with_nul_byte(db):
    # Mesmo raciocínio para o handshake GET: `hub.verify_token` é um query param de um chamador
    # anônimo (Meta ou qualquer um), e um NUL codificado (`%00`) chega intacto como `str`.
    assert inbox_service.resolve_by_verify_token(db, verify_token="tok\x00en") is None


def test_resolve_by_verify_token_rejects_verify_token_with_lone_surrogate(db):
    # Mesmo caso do surrogate solto, mas para o handshake GET. Note que isso é só um teste de
    # defesa em profundidade do `_is_safe_identifier`: na prática o `verify_token` chega como
    # query param de URL, e um surrogate inválido percent-decodificado vira `U+FFFD`, não um
    # surrogate de verdade — então esta entrada específica não é alcançável via HTTP real, mas a
    # guarda protege ainda assim caso o valor chegue por outro caminho (ex.: chamada direta).
    assert inbox_service.resolve_by_verify_token(db, verify_token="\ud800") is None


def test_ingest_creates_lead_for_unknown_number(db):
    _configure_credentials(db)
    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID, messages=meta.parse_inbound(_text_message_payload(
            phone_number_id="phone-123", wa_id="5511999999999",
            from_number="5511999999999", body="Oi, quero saber do cardápio",
        )),
    )
    client = db.scalar(select(Client).where(Client.phone == "5511999999999"))
    assert client is not None
    assert client.source == "whatsapp"
    msg = db.scalar(select(WhatsappMessage).where(WhatsappMessage.client_id == client.id))
    assert msg.direction == DIRECTION_IN
    assert msg.text_body == "Oi, quero saber do cardápio"


def test_ingest_records_audit_entry_for_received_message(db):
    _configure_credentials(db)
    existing = Client(tenant_id=TENANT_ID, name="Maria", phone="5511988880000", source="manual")
    db.add(existing)
    db.commit()
    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID, messages=meta.parse_inbound(_text_message_payload(
            phone_number_id="phone-123", wa_id="5511988880000",
            from_number="5511988880000", body="oi, já sou cliente",
        )),
    )
    audit_entry = db.scalar(
        select(AuditEntry).where(AuditEntry.action == "whatsapp_inbox.message.received")
    )
    assert audit_entry is not None
    assert audit_entry.target == existing.id


def test_ingest_reuses_existing_client_by_phone(db):
    _configure_credentials(db)
    existing = Client(tenant_id=TENANT_ID, name="Maria", phone="5511988887777", source="manual")
    db.add(existing)
    db.commit()
    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID, messages=meta.parse_inbound(_text_message_payload(
            phone_number_id="phone-123", wa_id="5511988887777",
            from_number="5511988887777", body="oi",
        )),
    )
    clients = db.scalars(select(Client).where(Client.phone == "5511988887777")).all()
    assert len(clients) == 1  # não duplicou


def test_ingest_is_idempotent_on_duplicate_wa_message_id(db):
    _configure_credentials(db)
    payload = _text_message_payload(
        phone_number_id="phone-123", wa_id="5511977776666",
        from_number="5511977776666", body="oi", msg_id="wamid.dup",
    )
    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID, messages=meta.parse_inbound(payload)
    )
    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID, messages=meta.parse_inbound(payload)
    )
    all_rows = db.scalars(
        select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "wamid.dup")
    ).all()
    assert len(all_rows) == 1


def test_ingest_image_message_marks_media_pending(db):
    _configure_credentials(db)
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "metadata": {"phone_number_id": "phone-123"},
                    "contacts": [{"profile": {"name": "Cliente"}, "wa_id": "5511911112222"}],
                    "messages": [{
                        "from": "5511911112222", "id": "wamid.img", "type": "image",
                        "image": {"id": "media-999", "mime_type": "image/jpeg"},
                    }],
                },
                "field": "messages",
            }],
        }],
    }
    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID, messages=meta.parse_inbound(payload)
    )
    msg = db.scalar(select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "wamid.img"))
    assert msg.kind == "image"
    assert msg.media_status == MEDIA_STATUS_PENDING


def test_ingest_evolution_media_creates_attachment_synchronously(db):
    # Evolution entrega bytes já decodificados (webhookBase64) — diferente do fluxo Meta acima
    # (media_ref opaco + worker assíncrono), o Attachment é criado NA HORA, dentro do próprio
    # ingest_webhook_payload.
    _configure_credentials(db)
    msg = InboundMessage(
        wa_message_id="3EB0IMG1", from_phone="5511922223333", kind="image",
        text_body="olha essa foto", media_ref=None, push_name="Cliente Evolution",
        media_bytes=b"fake-jpeg-bytes", media_mime_type="image/jpeg",
        media_filename=None,
    )
    inbox_service.ingest_webhook_payload(db, tenant_id=TENANT_ID, messages=[msg])

    row = db.scalar(select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "3EB0IMG1"))
    assert row is not None
    assert row.media_status == MEDIA_STATUS_DOWNLOADED
    assert row.media_attachment_id is not None
    assert row.text_body == "olha essa foto"

    attachment = db.get(Attachment, row.media_attachment_id)
    assert attachment is not None
    assert attachment.content_type == "image/jpeg"
    assert attachment.owner_type == "whatsapp_message"
    assert attachment.owner_id == row.id


def test_ingest_evolution_media_unknown_mime_falls_back_to_octet_stream(db):
    # .md e outros tipos exóticos não estão em ALLOWED_TYPES — cai pro genérico em vez de
    # rejeitar o anexo (mesmo padrão já usado no envio de resposta com mídia).
    _configure_credentials(db)
    msg = InboundMessage(
        wa_message_id="3EB0DOC1", from_phone="5511922224444", kind="document",
        text_body="segue o arquivo", media_ref=None, push_name="Cliente Evolution",
        media_bytes=b"# markdown", media_mime_type="text/markdown",
        media_filename="learnings.md",
    )
    inbox_service.ingest_webhook_payload(db, tenant_id=TENANT_ID, messages=[msg])

    row = db.scalar(select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "3EB0DOC1"))
    attachment = db.get(Attachment, row.media_attachment_id)
    assert attachment.content_type == "application/octet-stream"
    assert attachment.filename == "learnings.md"


def test_ingest_evolution_media_over_size_limit_fails_gracefully(db):
    # Anexo grande demais: a mensagem AINDA é registrada (com legenda), só sem o anexo — mesmo
    # princípio de isolamento por mensagem do resto da função.
    _configure_credentials(db)
    msg = InboundMessage(
        wa_message_id="3EB0BIG1", from_phone="5511922225555", kind="image",
        text_body="foto gigante", media_ref=None, push_name="Cliente Evolution",
        media_bytes=b"x" * (11 * 1024 * 1024), media_mime_type="image/jpeg",
        media_filename=None,
    )
    inbox_service.ingest_webhook_payload(db, tenant_id=TENANT_ID, messages=[msg])

    row = db.scalar(select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "3EB0BIG1"))
    assert row is not None
    assert row.text_body == "foto gigante"
    assert row.media_status == MEDIA_STATUS_FAILED
    assert row.media_attachment_id is None


# NOTA (Onda 3): os testes de shape do LOTE malformado (`value` não-dict, `messages` não é uma
# lista de dicts) MOVERAM para tests/test_whatsapp_inbound_parsing.py
# (test_meta_parse_inbound_raises_on_non_dict_value,
# test_meta_parse_inbound_raises_when_messages_is_not_a_list_of_dicts) — essa validação agora
# vive em `meta.parse_inbound()`, chamado pelo router ANTES de `ingest_webhook_payload`, que só
# recebe `messages` já parseadas e válidas na forma.


def test_ingest_skips_malformed_text_field_without_crashing(db):
    # Isolamento por mensagem (review round 5): `text` é uma string, não um dict — o acesso
    # `.get("body")` quebraria. Em vez de derrubar a request inteira, a mensagem malformada é
    # logada e ignorada; nenhuma linha é criada para ela.
    _configure_credentials(db)
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "metadata": {"phone_number_id": "phone-123"},
                    "contacts": [{"profile": {"name": "Fulano"}, "wa_id": "5511900000001"}],
                    "messages": [{
                        "id": "w1", "from": "5511900000001", "type": "text",
                        "text": "not-a-dict",
                    }],
                },
                "field": "messages",
            }],
        }],
    }
    # não levanta
    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID, messages=meta.parse_inbound(payload)
    )
    assert db.scalar(
        select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "w1")
    ) is None


def test_ingest_skips_malformed_media_field_without_crashing(db):
    # Mesma isolação para mídia: `image` é uma string, não um dict.
    _configure_credentials(db)
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "metadata": {"phone_number_id": "phone-123"},
                    "contacts": [{"profile": {"name": "Fulano"}, "wa_id": "5511900000002"}],
                    "messages": [{
                        "id": "w2", "from": "5511900000002", "type": "image",
                        "image": "not-a-dict",
                    }],
                },
                "field": "messages",
            }],
        }],
    }
    # não levanta
    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID, messages=meta.parse_inbound(payload)
    )
    assert db.scalar(
        select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "w2")
    ) is None


def test_ingest_skips_message_with_non_string_contact_name(db):
    # `contacts[0].profile.name` é um dict aninhado (não uma string) — estruturalmente válido em
    # `_extract_messages`, mas quebra o `ClientCreate(name=...)` dentro de `_get_or_create_client`
    # com um pydantic.ValidationError. O `except Exception` por mensagem isola essa falha.
    _configure_credentials(db)
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "metadata": {"phone_number_id": "phone-123"},
                    "contacts": [{"profile": {"name": {"a": "b"}}, "wa_id": "5511900000003"}],
                    "messages": [{
                        "id": "w3", "from": "5511900000003", "type": "text",
                        "text": {"body": "oi"},
                    }],
                },
                "field": "messages",
            }],
        }],
    }
    # não levanta
    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID, messages=meta.parse_inbound(payload)
    )
    assert db.scalar(
        select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "w3")
    ) is None


def test_ingest_processes_valid_message_even_when_another_in_same_payload_is_malformed(db):
    # O TESTE-PAYOFF desta rodada: prova que o isolamento funciona ponta-a-ponta. Duas mensagens no
    # MESMO lote — uma malformada (`text` é string) e uma válida. A malformada é ignorada, a válida
    # é processada normalmente. Uma mensagem ruim NÃO bloqueia as outras válidas do mesmo lote.
    _configure_credentials(db)
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "metadata": {"phone_number_id": "phone-123"},
                    "contacts": [{"profile": {"name": "Fulano"}, "wa_id": "5511900000004"}],
                    "messages": [
                        {
                            "id": "bad-1", "from": "5511900000004", "type": "text",
                            "text": "not-a-dict",
                        },
                        {
                            "id": "good-1", "from": "5511900000004", "type": "text",
                            "text": {"body": "mensagem válida"},
                        },
                    ],
                },
                "field": "messages",
            }],
        }],
    }
    # não levanta
    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID, messages=meta.parse_inbound(payload)
    )

    assert db.scalar(
        select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "bad-1")
    ) is None
    good = db.scalar(
        select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "good-1")
    )
    assert good is not None
    assert good.text_body == "mensagem válida"


def test_ingest_persists_valid_message_after_earlier_message_fails_to_encode(db):
    # ISOLAMENTO EM NÍVEL DE PERSISTÊNCIA (review round 9): diferente do teste-payoff acima (que
    # prova isolação de uma falha de VALIDAÇÃO, pega por `isinstance` ANTES de qualquer `db.add`),
    # este prova isolação de uma falha na CAMADA DO BANCO. A primeira mensagem tem `text.body` com
    # um surrogate solto (`"\ud800"`): passa em TODAS as checagens Python (`text` É um dict, `body`
    # É uma string), então é staged com `db.add(...)` sem erro — mas o surrogate não codifica em
    # UTF-8, e o commit levanta (SQLite dá `UnicodeEncodeError` na hora do bind, mesma classe que o
    # psycopg daria em produção). Com um único commit no fim do laço, esse erro escaparia FORA de
    # todo try/except (500 não tratado) e/ou o rollback derrubaria a mensagem válida junto. Com
    # commit POR MENSAGEM, a falha da primeira é isolada em sua própria transação e a segunda,
    # válida e posterior no MESMO lote, sobrevive.
    _configure_credentials(db)
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "metadata": {"phone_number_id": "phone-123"},
                    "contacts": [{"profile": {"name": "Fulano"}, "wa_id": "5511900000005"}],
                    "messages": [
                        {
                            "id": "bad-encode-1", "from": "5511900000005", "type": "text",
                            "text": {"body": "\ud800"},
                        },
                        {
                            "id": "good-2", "from": "5511900000005", "type": "text",
                            "text": {"body": "mensagem válida de verdade"},
                        },
                    ],
                },
                "field": "messages",
            }],
        }],
    }
    # não levanta
    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID, messages=meta.parse_inbound(payload)
    )

    assert db.scalar(
        select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "bad-encode-1")
    ) is None
    good = db.scalar(
        select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "good-2")
    )
    assert good is not None
    assert good.text_body == "mensagem válida de verdade"



def _chat_for(db, client) -> WhatsappChat:
    """A conversa direta daquele contato — o que o ingest cria sozinho a partir do `remoteJid`.
    Nos testes precisa ser explícito porque eles inserem `WhatsappMessage` na mão, sem passar
    pelo webhook."""
    chat = WhatsappChat(
        tenant_id=TENANT_ID, chat_jid=f"{client.phone}@s.whatsapp.net", kind="direct",
        title=client.name, client_id=client.id,
    )
    db.add(chat)
    db.flush()
    return chat

def test_is_within_session_window_true_right_after_inbound(db):
    _configure_credentials(db)
    client = Client(tenant_id=TENANT_ID, name="Cliente", phone="5511900001111", source="manual")
    db.add(client)
    db.flush()
    chat = _chat_for(db, client)
    db.add(WhatsappMessage(
        tenant_id=TENANT_ID, client_id=client.id, chat_id=chat.id, direction=DIRECTION_IN,
        kind="text",
        text_body="oi",
    ))
    db.commit()
    assert inbox_service.is_within_session_window(db, chat_id=chat.id) is True


def test_is_within_session_window_false_when_never_messaged(db):
    _configure_credentials(db)
    client = Client(tenant_id=TENANT_ID, name="Cliente", phone="5511900002222", source="manual")
    db.add(client)
    db.flush()
    chat = _chat_for(db, client)
    db.commit()
    assert inbox_service.is_within_session_window(db, chat_id=chat.id) is False


def test_get_timeline_merges_conversation_and_automated(db):
    _configure_credentials(db)
    client = Client(tenant_id=TENANT_ID, name="Cliente", phone="5511900003333", source="manual")
    db.add(client)
    db.flush()
    chat = _chat_for(db, client)
    db.add(WhatsappMessage(
        tenant_id=TENANT_ID, client_id=client.id, chat_id=chat.id, direction=DIRECTION_IN,
        kind="text",
        text_body="Oi",
    ))
    db.add(Notification(
        tenant_id=TENANT_ID, channel="whatsapp", recipient=client.phone, client_id=client.id,
        message="Lembrete: sua cobrança vence amanhã", status="sent",
    ))
    db.commit()
    timeline = inbox_service.get_timeline(db, chat_id=chat.id)
    sources = {e["source"] for e in timeline}
    assert sources == {"conversation", "automated"}


def test_send_reply_text_within_window(db, monkeypatch: pytest.MonkeyPatch):
    _configure_credentials(db)
    client = Client(tenant_id=TENANT_ID, name="Cliente", phone="5511900004444", source="manual")
    db.add(client)
    db.flush()
    chat = _chat_for(db, client)
    db.add(WhatsappMessage(
        tenant_id=TENANT_ID, client_id=client.id, chat_id=chat.id, direction=DIRECTION_IN,
        kind="text",
        text_body="oi",
    ))
    db.commit()

    captured = {}
    monkeypatch.setattr(
        whatsapp, "send_text",
        lambda **kw: (captured.update(kw), "sent")[1],
    )
    msg = inbox_service.send_reply_text(
        db, tenant_id=TENANT_ID, actor="user-1", chat_id=chat.id, text="Olá! Segue o cardápio.",
    )
    assert msg.direction == DIRECTION_OUT
    assert msg.status == "sent"
    assert captured["profile"].whatsapp_token == "tok"
    assert captured["profile"].whatsapp_phone_id == "phone-123"


def test_send_reply_text_raises_outside_window(db):
    _configure_credentials(db)
    client = Client(tenant_id=TENANT_ID, name="Cliente", phone="5511900005555", source="manual")
    db.add(client)
    db.flush()
    chat = _chat_for(db, client)
    db.commit()
    with pytest.raises(inbox_service.WhatsappInboxError):
        inbox_service.send_reply_text(
            db, tenant_id=TENANT_ID, actor="user-1", chat_id=chat.id, text="oi",
        )


def test_send_reply_media_rejects_disallowed_mime_type_before_sending(
    db, monkeypatch: pytest.MonkeyPatch
):
    _configure_credentials(db)
    client = Client(tenant_id=TENANT_ID, name="Cliente", phone="5511900005556", source="manual")
    db.add(client)
    db.flush()
    chat = _chat_for(db, client)
    db.add(WhatsappMessage(
        tenant_id=TENANT_ID, client_id=client.id, chat_id=chat.id, direction=DIRECTION_IN,
        kind="text",
        text_body="oi",
    ))
    db.commit()

    def _boom(*_a: object, **_k: object) -> None:  # pragma: no cover - não deve ser chamado
        raise AssertionError("upload_media não deveria ser chamado para mime_type reprovado")

    monkeypatch.setattr(whatsapp, "upload_media", _boom)

    with pytest.raises(inbox_service.WhatsappInboxError):
        inbox_service.send_reply_media(
            db, tenant_id=TENANT_ID, actor="user-1", chat_id=chat.id,
            file_bytes=b"fake-audio-bytes", filename="audio.mp3", mime_type="text/plain",
        )

    count = db.scalar(
        select(WhatsappMessage).where(
            WhatsappMessage.client_id == client.id, WhatsappMessage.direction == DIRECTION_OUT
        )
    )
    assert count is None  # nenhuma linha "sent" órfã foi criada


def test_send_reply_media_rejects_empty_file_before_sending(
    db, monkeypatch: pytest.MonkeyPatch
):
    _configure_credentials(db)
    client = Client(tenant_id=TENANT_ID, name="Cliente", phone="5511900005557", source="manual")
    db.add(client)
    db.flush()
    chat = _chat_for(db, client)
    db.add(WhatsappMessage(
        tenant_id=TENANT_ID, client_id=client.id, chat_id=chat.id, direction=DIRECTION_IN,
        kind="text",
        text_body="oi",
    ))
    db.commit()

    def _boom(*_a: object, **_k: object) -> None:  # pragma: no cover - não deve ser chamado
        raise AssertionError("upload_media não deveria ser chamado para arquivo vazio")

    monkeypatch.setattr(whatsapp, "upload_media", _boom)

    with pytest.raises(inbox_service.WhatsappInboxError):
        inbox_service.send_reply_media(
            db, tenant_id=TENANT_ID, actor="user-1", chat_id=chat.id,
            file_bytes=b"", filename="doc.pdf", mime_type="application/pdf",
        )

    count = db.scalar(
        select(WhatsappMessage).where(
            WhatsappMessage.client_id == client.id, WhatsappMessage.direction == DIRECTION_OUT
        )
    )
    assert count is None  # nenhuma linha "sent" órfã foi criada


def test_send_reply_media_success_creates_message_and_attachment(
    db, monkeypatch: pytest.MonkeyPatch
):
    _configure_credentials(db)
    client = Client(tenant_id=TENANT_ID, name="Cliente", phone="5511900005558", source="manual")
    db.add(client)
    db.flush()
    chat = _chat_for(db, client)
    db.add(WhatsappMessage(
        tenant_id=TENANT_ID, client_id=client.id, chat_id=chat.id, direction=DIRECTION_IN,
        kind="text",
        text_body="oi",
    ))
    db.commit()

    monkeypatch.setattr(whatsapp, "upload_media", lambda **_kw: "media-fake-1")
    monkeypatch.setattr(whatsapp, "send_media", lambda **_kw: "sent")

    msg = inbox_service.send_reply_media(
        db, tenant_id=TENANT_ID, actor="user-1", chat_id=chat.id,
        file_bytes=b"%PDF-1.4 fake pdf bytes", filename="cardapio.pdf",
        mime_type="application/pdf",
    )

    assert msg.status == "sent"
    assert msg.media_attachment_id is not None

    attachment = db.scalar(
        select(Attachment).where(
            Attachment.owner_type == "whatsapp_message", Attachment.owner_id == msg.id
        )
    )
    assert attachment is not None

    audit_entry = db.scalar(
        select(AuditEntry).where(AuditEntry.action == "whatsapp_inbox.reply.media")
    )
    assert audit_entry is not None


def test_send_reply_template_requires_approved_template(db):
    _configure_credentials(db)
    client = Client(tenant_id=TENANT_ID, name="Cliente", phone="5511900006666", source="manual")
    tpl = WhatsappTemplate(
        tenant_id=TENANT_ID, name="fora_janela", language="pt_BR",
        category_requested="UTILITY", status="PENDING", body_text="Olá {{1}}",
        variable_count=1, variable_examples=["Nome"],
    )
    db.add(client)
    db.add(tpl)
    db.flush()
    chat = _chat_for(db, client)
    db.commit()
    with pytest.raises(inbox_service.WhatsappInboxError) as exc_info:
        inbox_service.send_reply_template(
            db, tenant_id=TENANT_ID, actor="user-1", chat_id=chat.id,
            template_id=tpl.id, variables=["Fulano"],
        )
    assert "não aprovado" in str(exc_info.value)


def test_mark_read_marks_the_chat(db):
    _configure_credentials(db)
    client = Client(tenant_id=TENANT_ID, name="Cliente", phone="5511900007777", source="manual")
    db.add(client)
    db.flush()
    chat = _chat_for(db, client)
    db.commit()

    inbox_service.mark_read(db, tenant_id=TENANT_ID, chat_id=chat.id)

    assert chat.last_read_at is not None
    audit_entry = db.scalar(
        select(AuditEntry).where(AuditEntry.action == "whatsapp_inbox.conversation.mark_read")
    )
    assert audit_entry is not None
    assert audit_entry.target == chat.id


def test_mark_read_is_idempotent_under_concurrent_calls(db):
    """Substitui `test_mark_read_recovers_from_concurrent_insert_race`, que reproduzia um 500 de
    produção: clicar numa conversa dispara `/read` de mais de um lugar quase ao mesmo tempo (a
    lista E a thread), as duas requests viam `state is None` e tentavam INSERIR a mesma linha em
    `whatsapp_conversation_states`, e a última esbarrava em
    `uq_whatsapp_conv_state_tenant_client`.

    Essa corrida **deixou de existir por construção** na Onda 4: o estado de leitura passou a
    viver na própria conversa, que já existe quando `mark_read` roda. Não há INSERT — só dois
    UPDATEs do mesmo campo, e a última escrita vencer é o resultado certo. O teste que fica é o
    do comportamento observável: chamar duas vezes não levanta e não duplica nada."""
    _configure_credentials(db)
    client = Client(tenant_id=TENANT_ID, name="Cliente", phone="5511900006666", source="manual")
    db.add(client)
    db.flush()
    chat = _chat_for(db, client)
    db.commit()

    inbox_service.mark_read(db, tenant_id=TENANT_ID, chat_id=chat.id)
    primeiro = chat.last_read_at
    inbox_service.mark_read(db, tenant_id=TENANT_ID, chat_id=chat.id)  # não pode levantar

    assert chat.last_read_at is not None
    assert chat.last_read_at >= primeiro
    chats = db.scalars(select(WhatsappChat).where(WhatsappChat.client_id == client.id)).all()
    assert len(chats) == 1  # nada foi duplicado


def test_mark_read_unknown_chat_is_404(db):
    _configure_credentials(db)
    with pytest.raises(inbox_service.WhatsappInboxError) as exc_info:
        inbox_service.mark_read(db, tenant_id=TENANT_ID, chat_id="nao-existe")
    assert exc_info.value.status_code == 404
