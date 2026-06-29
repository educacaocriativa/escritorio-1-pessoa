"""Notificações: reage a eventos de negócio e dispara WhatsApp ao usuário (owner).

Assina `crm.client.moved` (barramento core/events). Como o evento é emitido após o commit
do move, abrimos uma nova tenant_session para gravar a notificação e enviar.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import events, whatsapp
from app.db.session import tenant_session
from app.modules.auth.models import User
from app.modules.crm.models import Client, PipelineStage
from app.modules.crm.service import EVENT_CLIENT_MOVED
from app.modules.notifications.models import Notification


def _owner_recipient(db: Session, tenant_id: str) -> str:
    owner = db.scalar(select(User).where(User.tenant_id == tenant_id, User.role == "owner"))
    return owner.email if owner else ""


def on_client_moved(*, tenant_id: str, client_id: str, to_stage: str, **_: object) -> None:
    with tenant_session(tenant_id) as db:
        client = db.get(Client, client_id)
        stage = db.get(PipelineStage, to_stage)
        name = client.name if client else "Cliente"
        col = stage.name if stage else "—"
        text = f'📌 O cliente {name} foi movido para a etapa "{col}".'
        recipient = _owner_recipient(db, tenant_id)
        status = whatsapp.send_text(to=recipient, text=text)
        db.add(
            Notification(
                tenant_id=tenant_id,
                channel="whatsapp",
                recipient=recipient,
                message=text,
                status=status,
            )
        )


def list_notifications(db: Session, limit: int = 50) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification).order_by(Notification.created_at.desc()).limit(limit)
        ).all()
    )


def register() -> None:
    """Liga os assinantes do barramento. Chamado uma vez no boot (app.main)."""
    events.subscribe(EVENT_CLIENT_MOVED, on_client_moved)
