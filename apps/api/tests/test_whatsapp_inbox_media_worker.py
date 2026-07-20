# apps/api/tests/test_whatsapp_inbox_media_worker.py
"""Download assíncrono de mídia pendente (worker) — mensagens recebidas com media_status=pending."""
import pytest

from app.core import whatsapp
from app.modules.crm.models import Client
from app.modules.settings import service as settings_service
from app.modules.whatsapp_inbox import service as inbox_service
from app.modules.whatsapp_inbox.models import (
    DIRECTION_IN,
    MEDIA_STATUS_DOWNLOADED,
    MEDIA_STATUS_FAILED,
    MEDIA_STATUS_PENDING,
    WhatsappMessage,
)

TENANT_ID = "33333333-3333-3333-3333-333333333333"


def _seed(db):
    profile = settings_service.get_profile(db, TENANT_ID)
    profile.whatsapp_token = "tok"
    profile.whatsapp_phone_id = "phone-1"
    db.commit()
    client = Client(tenant_id=TENANT_ID, name="Cliente", phone="5511900000009", source="manual")
    db.add(client)
    db.flush()
    msg = WhatsappMessage(
        tenant_id=TENANT_ID, client_id=client.id, direction=DIRECTION_IN, kind="image",
        media_status=MEDIA_STATUS_PENDING, wa_message_id="wamid.media1",
        meta_media_id="meta-media-1",
    )
    db.add(msg)
    db.commit()
    return msg


def test_process_pending_media_downloads_successfully(db, monkeypatch: pytest.MonkeyPatch):
    msg = _seed(db)
    monkeypatch.setattr(
        whatsapp, "fetch_media_url", lambda **_kw: "https://example.com/file.jpg"
    )
    monkeypatch.setattr(whatsapp, "download_media", lambda **_kw: b"fake-image-bytes")

    processed = inbox_service.process_pending_media(db, tenant_id=TENANT_ID)
    assert processed == 1
    db.refresh(msg)
    assert msg.media_status == MEDIA_STATUS_DOWNLOADED
    assert msg.media_attachment_id is not None


def test_process_pending_media_marks_failed_on_error(db, monkeypatch: pytest.MonkeyPatch):
    msg = _seed(db)

    def _boom(**_kw):
        raise whatsapp.WhatsappApiError("erro de rede")

    monkeypatch.setattr(whatsapp, "fetch_media_url", _boom)

    processed = inbox_service.process_pending_media(db, tenant_id=TENANT_ID)
    assert processed == 1
    db.refresh(msg)
    assert msg.media_status == MEDIA_STATUS_FAILED


def test_process_pending_media_noop_when_nothing_pending(db):
    profile = settings_service.get_profile(db, TENANT_ID)
    profile.whatsapp_token = "tok"
    profile.whatsapp_phone_id = "phone-1"
    db.commit()

    processed = inbox_service.process_pending_media(db, tenant_id=TENANT_ID)
    assert processed == 0
