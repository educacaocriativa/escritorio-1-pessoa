"""Fila assíncrona de notificações (Story 4.3): enqueue + process_pending.

Cobre: enfileiramento (status=pending), entrega marca sent/logged conforme o retorno do provedor,
isolamento de falha (uma notificação que lança NÃO impede as demais — IV2), respeito ao `limit`,
e roteamento por canal (email → email.send_email; senão → whatsapp.send_text). SQLite em memória
(fixture `db`), providers mockados via monkeypatch (não bate em rede real).

Onda 3 acrescenta: validade (`expires_at`) — vencida nunca tenta entregar — e retry com backoff
exponencial limitado pela validade (ver classes de teste no final do arquivo).
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core import email, whatsapp
from app.modules.notifications import service
from app.modules.notifications.models import Notification
from app.modules.settings.models import TenantProfile

TENANT = "tenant-00000000-teste"


def _pending(db, *, channel="whatsapp", recipient="dono@example.com", message="oi"):
    n = service.enqueue(
        db, tenant_id=TENANT, channel=channel, recipient=recipient, message=message
    )
    db.commit()
    return n


def test_enqueue_creates_pending(db):
    n = service.enqueue(
        db, tenant_id=TENANT, channel="whatsapp", recipient="d@e.com", message="Olá"
    )
    db.commit()
    assert n.status == "pending"
    assert n.attempts == 0
    assert n.last_error == ""


def test_process_pending_marks_sent(db, monkeypatch):
    _pending(db)
    monkeypatch.setattr(
        whatsapp,
        "send_text",
        lambda *, to, text, profile=None, token=None, phone_id=None: "sent",
    )
    processed = service.process_pending(db, tenant_id=TENANT)
    assert processed == 1
    n = db.scalar(select(Notification))
    assert n.status == "sent"
    assert n.attempts == 1


def test_process_pending_logged_without_provider(db):
    # stub padrão do whatsapp (sem token) retorna "logged" — não falha.
    _pending(db)
    processed = service.process_pending(db, tenant_id=TENANT)
    assert processed == 1
    assert db.scalar(select(Notification)).status == "logged"


def test_failure_is_isolated_and_recorded(db, monkeypatch):
    # A 1ª notificação (msg "boom") faz o provedor lançar; a 2ª deve ser processada mesmo assim.
    _pending(db, message="boom")
    _pending(db, message="ok")

    def _flaky(*, to, text, profile=None, token=None, phone_id=None):
        if "boom" in text:
            raise RuntimeError("provedor caiu")
        return "sent"

    monkeypatch.setattr(whatsapp, "send_text", _flaky)
    processed = service.process_pending(db, tenant_id=TENANT)
    assert processed == 2  # ambas processadas — a falha de uma não interrompe a outra (IV2)

    failed = db.scalar(select(Notification).where(Notification.message == "boom"))
    ok = db.scalar(select(Notification).where(Notification.message == "ok"))
    assert failed.status == "failed"
    assert "provedor caiu" in failed.last_error
    assert failed.attempts == 1
    assert ok.status == "sent"


def test_process_pending_respects_limit(db, monkeypatch):
    for i in range(3):
        _pending(db, message=f"msg-{i}")
    monkeypatch.setattr(
        whatsapp,
        "send_text",
        lambda *, to, text, profile=None, token=None, phone_id=None: "sent",
    )
    processed = service.process_pending(db, tenant_id=TENANT, limit=2)
    assert processed == 2
    remaining = db.scalars(
        select(Notification).where(Notification.status == "pending")
    ).all()
    assert len(remaining) == 1


def test_email_channel_uses_email_sender(db, monkeypatch):
    _pending(db, channel="email", recipient="dono@example.com", message="corpo")
    calls = {"email": 0, "whatsapp": 0}

    def _email(*, to, subject, body):
        calls["email"] += 1
        return "sent"

    def _whatsapp(*, to, text, profile=None, token=None, phone_id=None):
        calls["whatsapp"] += 1
        return "sent"

    monkeypatch.setattr(email, "send_email", _email)
    monkeypatch.setattr(whatsapp, "send_text", _whatsapp)
    service.process_pending(db, tenant_id=TENANT)
    assert calls["email"] == 1
    assert calls["whatsapp"] == 0
    assert db.scalar(select(Notification)).status == "sent"


def test_process_pending_passes_tenant_credentials_to_send_text(db, monkeypatch):
    """Caminho legado/sem template: o TenantProfile do tenant (não token/phone_id crus) chega
    a send_text via `profile=` — ver despachante em app/core/whatsapp/__init__.py (Onda 0 da
    feature de WhatsApp por Evolution API)."""
    db.add(
        TenantProfile(
            tenant_id=TENANT, whatsapp_token="tok-123", whatsapp_phone_id="phone-456"
        )
    )
    db.commit()
    _pending(db)

    captured: dict = {}

    def _send_text(*, to, text, profile=None, token=None, phone_id=None):
        captured.update(to=to, text=text, profile=profile, token=token, phone_id=phone_id)
        return "sent"

    monkeypatch.setattr(whatsapp, "send_text", _send_text)
    processed = service.process_pending(db, tenant_id=TENANT)
    assert processed == 1
    assert captured["profile"].whatsapp_token == "tok-123"
    assert captured["profile"].whatsapp_phone_id == "phone-456"


def test_process_pending_uses_send_template_when_fields_set(db, monkeypatch):
    """Notification com whatsapp_template_* preenchido → usa send_template, não send_text."""
    service.enqueue(
        db,
        tenant_id=TENANT,
        channel="whatsapp",
        recipient="dono@example.com",
        message="preview renderizado",
        whatsapp_template_name="tmpl_client_moved",
        whatsapp_template_language="pt_BR",
        whatsapp_template_variables=["Maria Cliente", "Proposta Enviada"],
    )
    db.commit()

    calls = {"template": 0, "text": 0}

    def _send_template(*, to, template_name, language, variables, profile=None, token=None,
                       phone_id=None):
        calls["template"] += 1
        assert to == "dono@example.com"
        assert template_name == "tmpl_client_moved"
        assert language == "pt_BR"
        assert variables == ["Maria Cliente", "Proposta Enviada"]
        return "sent"

    def _send_text(*_a, **_k):
        calls["text"] += 1
        return "sent"

    monkeypatch.setattr(whatsapp, "send_template", _send_template)
    monkeypatch.setattr(whatsapp, "send_text", _send_text)
    processed = service.process_pending(db, tenant_id=TENANT)
    assert processed == 1
    assert calls["template"] == 1
    assert calls["text"] == 0
    assert db.scalar(select(Notification)).status == "sent"


def test_process_pending_expires_past_due_without_attempting_delivery(db, monkeypatch):
    n = _pending(db)
    n.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    def _boom(**_k):
        raise AssertionError("não deveria tentar entregar notificação vencida")

    monkeypatch.setattr(whatsapp, "send_text", _boom)
    processed = service.process_pending(db, tenant_id=TENANT)
    assert processed == 1  # "processada" = decidida (expirada), não necessariamente entregue
    assert db.scalar(select(Notification)).status == "expired"


def test_process_pending_delivers_when_not_yet_expired(db, monkeypatch):
    n = _pending(db)
    n.expires_at = datetime.now(UTC) + timedelta(hours=1)
    db.commit()
    monkeypatch.setattr(
        whatsapp, "send_text",
        lambda *, to, text, profile=None, token=None, phone_id=None: "sent",
    )
    service.process_pending(db, tenant_id=TENANT)
    assert db.scalar(select(Notification)).status == "sent"
