"""Notificações: reage a eventos de negócio e enfileira envios ao usuário (owner) + fila async.

Assina `crm.client.moved` (barramento core/events). Como o evento é emitido após o commit
do move, abrimos uma nova tenant_session para ENFILEIRAR a notificação (status="pending"). A
entrega real (WhatsApp/e-mail) fica para o worker (`process_pending`, chamado por app.worker),
fora do request/response HTTP — assim uma falha de envio nunca derruba a request de origem (IV2,
Story 4.3).
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import email, events, whatsapp
from app.db.session import tenant_session
from app.modules.auth.models import User
from app.modules.crm.models import Client, PipelineStage
from app.modules.crm.service import EVENT_CLIENT_MOVED
from app.modules.notifications.models import Notification
from app.modules.settings import service as settings_service

logger = logging.getLogger("e1p.notifications")


def _owner_recipient(db: Session, tenant_id: str) -> str:
    """Telefone do owner/destinatário para o WhatsApp.

    Prioridade: TenantProfile.phone (editável na tela Configurações por qualquer owner) →
    User.phone (preenchido no fluxo de convite) → User.email (fallback final, preserva o
    placeholder histórico e a graceful degradation quando nenhum telefone foi configurado).
    """
    owner = db.scalar(select(User).where(User.tenant_id == tenant_id, User.role == "owner"))
    profile = settings_service.get_profile(db, tenant_id)
    if profile.phone:
        return profile.phone
    if owner and owner.phone:
        return owner.phone
    return owner.email if owner else ""


def enqueue(
    db: Session,
    *,
    tenant_id: str,
    channel: str,
    recipient: str,
    message: str,
    client_id: str | None = None,
) -> Notification:
    """Enfileira um envio (status="pending") — NÃO entrega agora nem commita.

    A entrega real acontece depois no worker (`process_pending`), fora do request/response HTTP.
    Segue o padrão das demais funções `service.*` que não commitam sozinhas: quem chama decide o
    commit dentro do seu fluxo maior.
    """
    notification = Notification(
        tenant_id=tenant_id,
        channel=channel,
        recipient=recipient,
        message=message,
        client_id=client_id,
        status="pending",
        attempts=0,
    )
    db.add(notification)
    db.flush()
    return notification


def process_pending(db: Session, *, tenant_id: str, limit: int = 50) -> int:
    """Processa a fila de notificações `pending` do tenant. Retorna quantas foram processadas.

    Chamado pelo worker (`app.worker.run_sweep`). Uma falha ao entregar UMA notificação NÃO
    interrompe as demais (IV2): cada envio é isolado em try/except e o erro fica registrado em
    `status="failed"`/`last_error`. Só reprocessa linhas `pending` — uma vez entregue (sent/logged)
    ou falha, a notificação sai do conjunto processável (idempotente; sem retry automático nesta
    story — `attempts`/`last_error` ficam para uma dívida futura de retry-with-backoff).
    """
    pending = list(
        db.scalars(
            select(Notification)
            .where(Notification.status == "pending")
            .order_by(Notification.created_at)
            .limit(limit)
        ).all()
    )
    processed = 0
    for notification in pending:
        try:
            if notification.channel == "email":
                status = email.send_email(
                    to=notification.recipient,
                    subject="Notificação e1p",
                    body=notification.message,
                )
            else:
                status = whatsapp.send_text(
                    to=notification.recipient, text=notification.message
                )
            notification.status = status
        except Exception as exc:  # noqa: BLE001 — isola a falha de UMA notificação (IV2)
            logger.exception(
                "[notifications:process_pending] falha ao enviar id=%s", notification.id
            )
            notification.status = "failed"
            notification.last_error = str(exc)[:500]
        notification.attempts += 1
        processed += 1
    db.commit()
    return processed


def on_client_moved(*, tenant_id: str, client_id: str, to_stage: str, **_: object) -> None:
    with tenant_session(tenant_id) as db:
        client = db.get(Client, client_id)
        stage = db.get(PipelineStage, to_stage)
        name = client.name if client else "Cliente"
        col = stage.name if stage else "—"
        text = f'📌 O cliente {name} foi movido para a etapa "{col}".'
        recipient = _owner_recipient(db, tenant_id)
        # Enfileira (status="pending") em vez de enviar síncrono aqui: o handler roda dentro da
        # MESMA request que moveu o card (crm.service.move_client → events.emit). A entrega real
        # (WhatsApp) fica para o worker (process_pending), sem bloquear a request (IV2).
        enqueue(
            db,
            tenant_id=tenant_id,
            channel="whatsapp",
            recipient=recipient,
            message=text,
            client_id=client_id,
        )
        db.commit()


def list_notifications(db: Session, limit: int = 50) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification).order_by(Notification.created_at.desc()).limit(limit)
        ).all()
    )


def register() -> None:
    """Liga os assinantes do barramento. Chamado uma vez no boot (app.main)."""
    events.subscribe(EVENT_CLIENT_MOVED, on_client_moved)
