"""Regras da Agenda: CRUD de eventos + detecção de conflitos de horário.

A sessão recebida já vem isolada por tenant (RLS) — não filtramos tenant manualmente nas
queries (Regra de Ouro nº 1). O tenant_id só é usado para CARIMBAR novas linhas.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core import audit
from app.modules.agenda.models import (
    OCCUPYING_KINDS,
    STATUS_CANCELLED,
    STATUS_DONE,
    AgendaEvent,
)
from app.modules.agenda.schemas import EventCreate, EventUpdate

# Estados terminais: não podem ser cancelados de novo nem remarcados.
TERMINAL_STATUSES = {STATUS_CANCELLED, STATUS_DONE}
DEFAULT_LIST_LIMIT = 200
MAX_LIST_LIMIT = 500


class AgendaError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def find_conflicts(
    db: Session,
    starts_at: datetime,
    ends_at: datetime,
    *,
    exclude_id: str | None = None,
) -> list[AgendaEvent]:
    """Eventos que OCUPAM tempo e se sobrepõem ao intervalo [starts_at, ends_at).

    Sobreposição: a.start < b.end AND b.start < a.end. Eventos cancelados são ignorados.
    """
    stmt = select(AgendaEvent).where(
        and_(
            AgendaEvent.kind.in_(OCCUPYING_KINDS),
            AgendaEvent.status != STATUS_CANCELLED,
            AgendaEvent.starts_at < ends_at,
            starts_at < AgendaEvent.ends_at,
        )
    )
    if exclude_id is not None:
        stmt = stmt.where(AgendaEvent.id != exclude_id)
    return list(db.scalars(stmt).all())


def create_event(
    db: Session, *, tenant_id: str, actor: str, by_ai: bool, data: EventCreate
) -> tuple[AgendaEvent, list[AgendaEvent]]:
    starts_at = data.starts_at
    ends_at = data.ends_at

    if data.all_day:
        # Ancora o evento de dia inteiro na meia-noite REAL do fuso do tenant (convertida p/ UTC),
        # em vez da meia-noite UTC crua. Import lazy de settings.get_profile p/ não acoplar o
        # módulo-núcleo Agenda ao módulo settings (mesmo padrão de quotes→contracts no CLAUDE.md).
        from app.core.tz import day_window_utc
        from app.modules.settings.service import get_profile

        profile = get_profile(db, tenant_id)
        starts_at, ends_at = day_window_utc(data.starts_at.date(), profile.timezone)

    conflicts: list[AgendaEvent] = []
    if data.kind in OCCUPYING_KINDS:
        conflicts = find_conflicts(db, starts_at, ends_at)

    event = AgendaEvent(
        tenant_id=tenant_id,
        title=data.title,
        description=data.description,
        kind=data.kind,
        priority=data.priority,
        source=data.source,
        starts_at=starts_at,
        ends_at=ends_at,
        all_day=data.all_day,
        location=data.location,
        meeting_url=data.meeting_url,
        guests=data.guests,
        amount_cents=data.amount_cents,
        external_ref=data.external_ref,
        created_by_ai=by_ai,
    )
    db.add(event)
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="agenda.event.create",
        target=event.id, is_ai=by_ai,
    )
    db.commit()
    db.refresh(event)
    return event, conflicts


def list_events(
    db: Session,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    kinds: list[str] | None = None,
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
) -> list[AgendaEvent]:
    # Módulo-núcleo: o volume cresce (cobranças/prazos injetam eventos). Sempre paginar.
    limit = max(1, min(limit, MAX_LIST_LIMIT))
    offset = max(0, offset)
    stmt = select(AgendaEvent)
    if start is not None:
        stmt = stmt.where(AgendaEvent.ends_at >= start)
    if end is not None:
        stmt = stmt.where(AgendaEvent.starts_at <= end)
    if kinds:
        stmt = stmt.where(AgendaEvent.kind.in_(kinds))
    stmt = stmt.order_by(AgendaEvent.starts_at).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def count_events(
    db: Session,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    kinds: list[str] | None = None,
    exclude_cancelled: bool = True,
) -> int:
    """Conta eventos na janela SEM cap de paginação (para KPIs corretos)."""
    stmt = select(func.count(AgendaEvent.id))
    if start is not None:
        stmt = stmt.where(AgendaEvent.ends_at >= start)
    if end is not None:
        stmt = stmt.where(AgendaEvent.starts_at <= end)
    if kinds:
        stmt = stmt.where(AgendaEvent.kind.in_(kinds))
    if exclude_cancelled:
        stmt = stmt.where(AgendaEvent.status != STATUS_CANCELLED)
    return db.scalar(stmt) or 0


def get_event(db: Session, event_id: str) -> AgendaEvent:
    event = db.get(AgendaEvent, event_id)
    if event is None:
        raise AgendaError("Evento não encontrado", 404)
    return event


def update_event(
    db: Session, *, event_id: str, tenant_id: str, actor: str, data: EventUpdate,
    by_ai: bool = False,
) -> AgendaEvent:
    event = get_event(db, event_id)
    if data.title is not None:
        event.title = data.title
    if data.description is not None:
        event.description = data.description
    if data.status is not None:
        event.status = data.status
    if data.priority is not None:
        event.priority = data.priority
    if data.location is not None:
        event.location = data.location
    if data.meeting_url is not None:
        event.meeting_url = data.meeting_url
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="agenda.event.update", target=event.id,
        is_ai=by_ai,
    )
    db.commit()
    db.refresh(event)
    return event


def cancel_event(
    db: Session, *, event_id: str, tenant_id: str, actor: str, by_ai: bool = False
) -> AgendaEvent:
    event = get_event(db, event_id)
    if event.status in TERMINAL_STATUSES:
        raise AgendaError("Evento já finalizado ou cancelado", 409)
    event.status = STATUS_CANCELLED
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="agenda.event.cancel", target=event.id,
        is_ai=by_ai,
    )
    db.commit()
    db.refresh(event)
    return event


def reschedule_event(
    db: Session,
    *,
    event_id: str,
    tenant_id: str,
    actor: str,
    starts_at: datetime,
    ends_at: datetime,
    by_ai: bool = False,
) -> tuple[AgendaEvent, list[AgendaEvent]]:
    event = get_event(db, event_id)
    if event.status in TERMINAL_STATUSES:
        raise AgendaError("Não é possível remarcar evento finalizado ou cancelado", 409)
    conflicts: list[AgendaEvent] = []
    if event.kind in OCCUPYING_KINDS:
        conflicts = find_conflicts(db, starts_at, ends_at, exclude_id=event.id)
    event.starts_at = starts_at
    event.ends_at = ends_at
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="agenda.event.reschedule", target=event.id,
        is_ai=by_ai,
    )
    db.commit()
    db.refresh(event)
    return event, conflicts
