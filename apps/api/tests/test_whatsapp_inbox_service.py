# apps/api/tests/test_whatsapp_inbox_service.py
"""Testes do serviço do inbox de WhatsApp: ingestão do webhook, lead automático, timeline
unificada, janela de 24h, resposta (texto/mídia/template)."""
import pytest
from sqlalchemy import select

from app.core import whatsapp
from app.modules.crm.models import Client
from app.modules.notifications.models import Notification
from app.modules.settings import service as settings_service
from app.modules.settings.models import TenantProfile
from app.modules.whatsapp_inbox import service as inbox_service
from app.modules.whatsapp_inbox.models import (
    DIRECTION_IN,
    DIRECTION_OUT,
    MEDIA_STATUS_PENDING,
    PublicWhatsappAccount,
    WhatsappConversationState,
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


def test_ingest_creates_lead_for_unknown_number(db):
    _configure_credentials(db)
    inbox_service.ingest_webhook_payload(
        db, payload=_text_message_payload(
            phone_number_id="phone-123", wa_id="5511999999999",
            from_number="5511999999999", body="Oi, quero saber do cardápio",
        ),
    )
    client = db.scalar(select(Client).where(Client.phone == "5511999999999"))
    assert client is not None
    assert client.source == "whatsapp"
    msg = db.scalar(select(WhatsappMessage).where(WhatsappMessage.client_id == client.id))
    assert msg.direction == DIRECTION_IN
    assert msg.text_body == "Oi, quero saber do cardápio"


def test_ingest_reuses_existing_client_by_phone(db):
    _configure_credentials(db)
    existing = Client(tenant_id=TENANT_ID, name="Maria", phone="5511988887777", source="manual")
    db.add(existing)
    db.commit()
    inbox_service.ingest_webhook_payload(
        db, payload=_text_message_payload(
            phone_number_id="phone-123", wa_id="5511988887777",
            from_number="5511988887777", body="oi",
        ),
    )
    clients = db.scalars(select(Client).where(Client.phone == "5511988887777")).all()
    assert len(clients) == 1  # não duplicou


def test_ingest_is_idempotent_on_duplicate_wa_message_id(db):
    _configure_credentials(db)
    payload = _text_message_payload(
        phone_number_id="phone-123", wa_id="5511977776666",
        from_number="5511977776666", body="oi", msg_id="wamid.dup",
    )
    inbox_service.ingest_webhook_payload(db, payload=payload)
    inbox_service.ingest_webhook_payload(db, payload=payload)
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
    inbox_service.ingest_webhook_payload(db, payload=payload)
    msg = db.scalar(select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "wamid.img"))
    assert msg.kind == "image"
    assert msg.media_status == MEDIA_STATUS_PENDING


def test_is_within_session_window_true_right_after_inbound(db):
    _configure_credentials(db)
    client = Client(tenant_id=TENANT_ID, name="Cliente", phone="5511900001111", source="manual")
    db.add(client)
    db.flush()
    db.add(WhatsappMessage(
        tenant_id=TENANT_ID, client_id=client.id, direction=DIRECTION_IN, kind="text",
        text_body="oi",
    ))
    db.commit()
    assert inbox_service.is_within_session_window(db, client_id=client.id) is True


def test_is_within_session_window_false_when_never_messaged(db):
    _configure_credentials(db)
    client = Client(tenant_id=TENANT_ID, name="Cliente", phone="5511900002222", source="manual")
    db.add(client)
    db.commit()
    assert inbox_service.is_within_session_window(db, client_id=client.id) is False


def test_get_timeline_merges_conversation_and_automated(db):
    _configure_credentials(db)
    client = Client(tenant_id=TENANT_ID, name="Cliente", phone="5511900003333", source="manual")
    db.add(client)
    db.flush()
    db.add(WhatsappMessage(
        tenant_id=TENANT_ID, client_id=client.id, direction=DIRECTION_IN, kind="text",
        text_body="Oi",
    ))
    db.add(Notification(
        tenant_id=TENANT_ID, channel="whatsapp", recipient=client.phone, client_id=client.id,
        message="Lembrete: sua cobrança vence amanhã", status="sent",
    ))
    db.commit()
    timeline = inbox_service.get_timeline(db, client_id=client.id)
    sources = {e["source"] for e in timeline}
    assert sources == {"conversation", "automated"}


def test_send_reply_text_within_window(db, monkeypatch: pytest.MonkeyPatch):
    _configure_credentials(db)
    client = Client(tenant_id=TENANT_ID, name="Cliente", phone="5511900004444", source="manual")
    db.add(client)
    db.flush()
    db.add(WhatsappMessage(
        tenant_id=TENANT_ID, client_id=client.id, direction=DIRECTION_IN, kind="text",
        text_body="oi",
    ))
    db.commit()

    captured = {}
    monkeypatch.setattr(
        whatsapp, "send_text",
        lambda **kw: (captured.update(kw), "sent")[1],
    )
    msg = inbox_service.send_reply_text(
        db, tenant_id=TENANT_ID, actor="user-1", client_id=client.id, text="Olá! Segue o cardápio.",
    )
    assert msg.direction == DIRECTION_OUT
    assert msg.status == "sent"
    assert captured["token"] == "tok"
    assert captured["phone_id"] == "phone-123"


def test_send_reply_text_raises_outside_window(db):
    _configure_credentials(db)
    client = Client(tenant_id=TENANT_ID, name="Cliente", phone="5511900005555", source="manual")
    db.add(client)
    db.commit()
    with pytest.raises(inbox_service.WhatsappInboxError):
        inbox_service.send_reply_text(
            db, tenant_id=TENANT_ID, actor="user-1", client_id=client.id, text="oi",
        )


def test_send_reply_template_requires_approved_template(db):
    _configure_credentials(db)
    client = Client(tenant_id=TENANT_ID, name="Cliente", phone="5511900006666", source="manual")
    tpl = WhatsappTemplate(
        tenant_id=TENANT_ID, name="fora_janela", language="pt_BR",
        category_requested="UTILITY", status="PENDING", body_text="Olá {{1}}",
        variable_count=1, variable_examples=["Nome"],
    )
    db.add(tpl)
    db.commit()
    with pytest.raises(inbox_service.WhatsappInboxError):
        inbox_service.send_reply_template(
            db, tenant_id=TENANT_ID, actor="user-1", client_id=client.id,
            template_id=tpl.id, variables=["Fulano"],
        )


def test_mark_read_updates_state(db):
    _configure_credentials(db)
    client = Client(tenant_id=TENANT_ID, name="Cliente", phone="5511900007777", source="manual")
    db.add(client)
    db.commit()
    inbox_service.mark_read(db, tenant_id=TENANT_ID, client_id=client.id)
    state = db.scalar(
        select(WhatsappConversationState).where(
            WhatsappConversationState.client_id == client.id
        )
    )
    assert state is not None
    assert state.last_read_at is not None
