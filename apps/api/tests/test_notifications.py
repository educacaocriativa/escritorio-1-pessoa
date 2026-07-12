"""Testes de notificação. A entrega real (subscriber + Postgres) é coberta no e2e Docker.

Os status de `send_text` (logged/sent/failed) são cobertos em `test_whatsapp.py`; aqui focamos
na resolução do destinatário (`_owner_recipient`) — a lógica que muda na Story 2.3 — e no
enfileiramento assíncrono (Story 4.3): mover card só cria uma Notification pending.
"""
from contextlib import contextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import whatsapp
from app.core.security import hash_password
from app.modules.auth.models import Tenant, User
from app.modules.notifications import service
from app.modules.notifications.models import Notification
from app.modules.notifications.service import NotificationError
from app.modules.settings.models import TenantProfile


def test_whatsapp_logged_without_config():
    # sem WHATSAPP_TOKEN/PHONE_ID configurados, o envio não falha: retorna "logged".
    assert whatsapp.send_text(to="5511999999999", text="oi") == "logged"


# ── Resolução do destinatário (_owner_recipient) ───────────────────────────────
# Fallback: TenantProfile.phone → User.phone → User.email.


def _make_owner(db: Session, *, phone: str | None = None) -> Tenant:
    tenant = Tenant(slug="acme", legal_name="Acme LTDA", document="12345678000199")
    db.add(tenant)
    db.flush()
    db.add(
        User(
            tenant_id=tenant.id,
            email="dono@acme.com",
            name="Dono",
            password_hash=hash_password("senha-bem-grande"),
            role="owner",
            phone=phone,
        )
    )
    db.commit()
    return tenant


def test_recipient_prefers_profile_phone(db: Session):
    # TenantProfile.phone tem prioridade sobre User.phone e o e-mail.
    tenant = _make_owner(db, phone="5511777770000")
    db.add(TenantProfile(tenant_id=tenant.id, phone="5511999990000"))
    db.commit()
    assert service._owner_recipient(db, tenant.id) == "5511999990000"


def test_recipient_falls_back_to_user_phone(db: Session):
    # Sem telefone no perfil (get_profile cria com phone=""), usa User.phone.
    tenant = _make_owner(db, phone="5511777770000")
    assert service._owner_recipient(db, tenant.id) == "5511777770000"


def test_recipient_falls_back_to_email(db: Session):
    # Sem telefone no perfil nem no usuário, cai no e-mail (placeholder histórico).
    tenant = _make_owner(db, phone=None)
    assert service._owner_recipient(db, tenant.id) == "dono@acme.com"


def _seed_owner_tenant(db, *, slug, document, email="dono@mov.com") -> Tenant:
    tenant = Tenant(slug=slug, legal_name="Mov SA", document=document)
    db.add(tenant)
    db.flush()
    db.add(
        User(
            tenant_id=tenant.id,
            email=email,
            name="Dono",
            password_hash="x",
            role="owner",
        )
    )
    db.commit()
    return tenant


def test_on_client_moved_enqueues_pending_for_existing_client(db, monkeypatch):
    """Fluxo feliz (Story 4.3 + 7.11): cliente EXISTENTE → enfileira `pending`, sem envio síncrono.

    on_client_moved apenas cria uma Notification pending; a entrega real fica p/ o worker (IV2).
    """
    from app.modules.crm.models import Client

    tenant = _seed_owner_tenant(db, slug="mov", document="00000000000191")
    client = Client(tenant_id=tenant.id, name="Maria Cliente")
    db.add(client)
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

    service.on_client_moved(tenant_id=tenant.id, client_id=client.id, to_stage="nao-existe")

    notif = db.scalar(select(Notification))
    assert notif is not None
    assert notif.status == "pending"
    assert notif.channel == "whatsapp"
    assert notif.recipient == "dono@mov.com"
    assert "Maria Cliente" in notif.message  # usa o nome real, não o placeholder
    assert called["whatsapp"] == 0  # NÃO enviou síncrono — só enfileirou


def test_on_client_moved_nonexistent_client_is_not_enqueued(db, monkeypatch):
    """Caminho infeliz (Story 7.11): cliente INEXISTENTE → NÃO enfileira (comportamento explícito).

    Antes (bug documentado sem intenção pelo teste antigo): seguia com name="Cliente" e criava
    uma Notification `pending` indistinguível de um caso real — sucesso silencioso. Agora
    on_client_moved curto-circuita: nenhuma Notification é criada para um client_id inexistente.
    """
    tenant = _seed_owner_tenant(db, slug="mov2", document="00000000000272")

    @contextmanager
    def _fake_tenant_session(_tenant_id):
        yield db

    monkeypatch.setattr(service, "tenant_session", _fake_tenant_session)

    service.on_client_moved(tenant_id=tenant.id, client_id="nao-existe", to_stage="nao-existe")

    # Nenhuma notificação enfileirada — não há sucesso silencioso.
    assert db.scalar(select(Notification)) is None


def test_enqueue_rejects_empty_recipient(db):
    """Caminho infeliz (Story 7.11): enqueue com recipient="" é REJEITADO explicitamente.

    Distinto de test_notifications_queue.py::test_failure_is_isolated_and_recorded (falha do
    PROVEDOR de entrega) — aqui é entrada inválida na ORIGEM, capturada antes de virar `pending`.
    """
    with pytest.raises(NotificationError):
        service.enqueue(
            db, tenant_id="t-1", channel="whatsapp", recipient="", message="oi"
        )
    # também rejeita whitespace-only
    with pytest.raises(NotificationError):
        service.enqueue(
            db, tenant_id="t-1", channel="whatsapp", recipient="   ", message="oi"
        )
    # nada foi enfileirado
    assert db.scalar(select(Notification)) is None
