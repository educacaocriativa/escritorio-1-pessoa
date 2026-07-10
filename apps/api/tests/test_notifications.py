"""Testes de notificação. A entrega real (subscriber + Postgres) é coberta no e2e Docker."""
from contextlib import contextmanager

from sqlalchemy import select

from app.core import whatsapp
from app.modules.auth.models import Tenant, User
from app.modules.notifications import service
from app.modules.notifications.models import Notification


def test_whatsapp_logged_without_config():
    # sem WHATSAPP_TOKEN/PHONE_ID configurados, o envio não falha: retorna "logged".
    assert whatsapp.send_text(to="5511999999999", text="oi") == "logged"


def test_on_client_moved_enqueues_pending_without_sending(db, monkeypatch):
    """Story 4.3: mover card só ENFILEIRA (status=pending); o envio real fica p/ o worker.

    Antes, on_client_moved chamava whatsapp.send_text de forma síncrona dentro da request. Agora
    ele apenas cria uma Notification pending — a entrega acontece depois em process_pending (IV2).
    """
    tenant = Tenant(slug="mov", legal_name="Mov SA", document="00000000000191")
    db.add(tenant)
    db.flush()
    db.add(
        User(
            tenant_id=tenant.id,
            email="dono@mov.com",
            name="Dono",
            password_hash="x",
            role="owner",
        )
    )
    db.commit()

    @contextmanager
    def _fake_tenant_session(_tenant_id):
        yield db

    monkeypatch.setattr(service, "tenant_session", _fake_tenant_session)

    called = {"whatsapp": 0}
    monkeypatch.setattr(
        whatsapp,
        "send_text",
        lambda *, to, text: called.__setitem__("whatsapp", called["whatsapp"] + 1) or "sent",
    )

    service.on_client_moved(tenant_id=tenant.id, client_id="nao-existe", to_stage="nao-existe")

    notif = db.scalar(select(Notification))
    assert notif is not None
    assert notif.status == "pending"
    assert notif.channel == "whatsapp"
    assert notif.recipient == "dono@mov.com"
    assert called["whatsapp"] == 0  # NÃO enviou síncrono — só enfileirou
