# apps/api/tests/test_whatsapp_inbox_media_worker.py
"""Download assíncrono de mídia pendente (worker) — mensagens recebidas com media_status=pending."""
import pytest

from app.core import whatsapp
from app.modules.attachments import service as attachments_service
from app.modules.attachments.models import Attachment
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


def _seed(db, *, wa_message_id="wamid.media1", meta_media_id="meta-media-1"):
    profile = settings_service.get_profile(db, TENANT_ID)
    profile.whatsapp_token = "tok"
    profile.whatsapp_phone_id = "phone-1"
    db.commit()
    client = Client(tenant_id=TENANT_ID, name="Cliente", phone="5511900000009", source="manual")
    db.add(client)
    db.flush()
    msg = WhatsappMessage(
        tenant_id=TENANT_ID, client_id=client.id, direction=DIRECTION_IN, kind="image",
        media_status=MEDIA_STATUS_PENDING, wa_message_id=wa_message_id,
        meta_media_id=meta_media_id,
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


def test_process_pending_media_isolates_failure_between_messages(
    db, monkeypatch: pytest.MonkeyPatch
):
    """Reproduz o cenário exato do finding: `create_attachment` (chamado DENTRO do try de
    `process_pending_media`) faz seu PRÓPRIO `db.commit()` internamente. Se esse commit falhar no
    meio (erro real de persistência — aqui simulado por uma violação de NOT NULL, mas na vida real
    seria um erro transitório de rede/storage/driver para bytes de mídia genuínos de vários MB), a
    Session do SQLAlchemy 2.0 fica "poisoned": qualquer uso subsequente (inclusive o
    `db.add`/commit da PRÓXIMA mensagem do mesmo lote) levanta `PendingRollbackError` a menos que
    um `db.rollback()` explícito rode primeiro.

    Por isso a falha é injetada aqui em `attachments_service.create_attachment` (o passo que
    REALMENTE persiste/committa), não em `whatsapp.fetch_media_url`/`download_media` (que só
    lançam uma exceção Python, sem tocar a Session — não reproduzem o "poisoning" real; validado
    manualmente: uma versão anterior deste teste que falhava só no fetch_media_url PASSAVA mesmo
    contra o código pré-fix, porque nenhuma escrita tinha ocorrido ainda para a Session
    'envenenar').

    Ordem importa: a mensagem que FALHA vem primeiro. Sem o `db.rollback()` do fix, a falha da
    primeira mensagem cascateia e o `create_attachment` da segunda (bem-sucedida) explode com
    `PendingRollbackError` — capturado pelo `except Exception` genérico e mascarado como
    `MEDIA_STATUS_FAILED`, quando deveria ter sido `MEDIA_STATUS_DOWNLOADED`."""
    failing_msg = _seed(db, wa_message_id="wamid.media-fail", meta_media_id="meta-media-fail")
    ok_msg = _seed(db, wa_message_id="wamid.media-ok", meta_media_id="meta-media-ok")

    monkeypatch.setattr(
        whatsapp, "fetch_media_url", lambda **_kw: "https://example.com/file.jpg"
    )
    monkeypatch.setattr(whatsapp, "download_media", lambda **_kw: b"fake-image-bytes")

    real_create_attachment = attachments_service.create_attachment

    def _create_attachment_side_effect(db_, **kwargs):
        if kwargs["owner_id"] == failing_msg.id:
            # Simula uma falha de PERSISTÊNCIA real (não uma exceção Python solta): grava um
            # Attachment com campo NOT NULL ausente e commita — o commit() levanta IntegrityError
            # de verdade, deixando a Session no mesmo estado "precisa de rollback" que um erro
            # transitório de driver/rede deixaria numa falha real de storage/DB.
            bad = Attachment(
                tenant_id=kwargs["tenant_id"], owner_type=kwargs["owner_type"],
                owner_id=kwargs["owner_id"], label="outro",
                filename=None, content_type=None, size=0,
            )
            db_.add(bad)
            db_.commit()  # IntegrityError real (NOT NULL) — Session fica poisoned sem rollback
            return bad  # nunca alcançado
        return real_create_attachment(db_, **kwargs)

    monkeypatch.setattr(attachments_service, "create_attachment", _create_attachment_side_effect)

    processed = inbox_service.process_pending_media(db, tenant_id=TENANT_ID)
    assert processed == 2

    db.refresh(failing_msg)
    db.refresh(ok_msg)
    assert failing_msg.media_status == MEDIA_STATUS_FAILED
    assert ok_msg.media_status == MEDIA_STATUS_DOWNLOADED
    assert ok_msg.media_attachment_id is not None
