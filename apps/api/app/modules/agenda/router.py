"""Rotas da Agenda. Todas exigem tenant autenticado + permissão ao módulo 'agenda'."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.agenda import service
from app.modules.agenda.models import AgendaEvent
from app.modules.agenda.schemas import (
    CreateEventResult,
    EventCreate,
    EventOut,
    EventUpdate,
    RescheduleRequest,
)
from app.modules.crm.models import Client
from app.modules.payables.models import Payable


def _events_out(db: Session, events: list[AgendaEvent]) -> list[EventOut]:
    """Resolve o nome exibido no card: cliente (vínculo direto) / fornecedor (derivação).

    Os dois caminhos existem porque são coisas diferentes. Cliente é VÍNCULO: o evento carrega
    `client_id` (Tasks 1/2 desta onda — backfill do passado + escrita no nascimento), então o nome
    vem de um join direto por id, sem passar por `external_ref`/`Charge`. Fornecedor CONTINUA
    sendo DERIVAÇÃO: conta a pagar não tem cliente e nunca terá `client_id` — o nome só existe
    porque `Payable.supplier` é alcançável via `external_ref`. Remover este segundo caminho
    apagaria o nome do fornecedor da tela da Agenda.
    """
    client_ids = {e.client_id for e in events if e.client_id}
    names: dict[str, str] = {}
    if client_ids:
        rows = db.scalars(select(Client).where(Client.id.in_(client_ids)))
        names = {c.id: c.name for c in rows}

    pagar_refs = [e.external_ref for e in events if e.kind == "cobranca_pagar" and e.external_ref]
    supplier_names: dict[str, str] = {}
    if pagar_refs:
        for p in db.scalars(select(Payable).where(Payable.id.in_(pagar_refs))):
            if p.supplier:
                supplier_names[p.id] = p.supplier

    out = []
    for e in events:
        eo = EventOut.model_validate(e)
        if e.client_id:
            eo.client_name = names.get(e.client_id)
        elif e.external_ref:
            eo.client_name = supplier_names.get(e.external_ref)
        else:
            eo.client_name = None
        out.append(eo)
    return out

router = APIRouter(prefix="/agenda", tags=["agenda"])

_guard = require_module("agenda")


@router.post("/events", response_model=CreateEventResult, status_code=201)
def create_event(
    data: EventCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> CreateEventResult:
    event, conflicts = service.create_event(
        db, tenant_id=user.tenant_id, actor=user.user_id, by_ai=user.is_ai, data=data
    )
    return CreateEventResult(
        event=EventOut.model_validate(event),
        conflicts=[EventOut.model_validate(c) for c in conflicts],
    )


@router.get("/events", response_model=list[EventOut])
def list_events(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    kind: list[str] | None = Query(default=None),
    client_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[EventOut]:
    events = service.list_events(
        db, start=start, end=end, kinds=kind, client_id=client_id, limit=limit, offset=offset
    )
    return _events_out(db, events)


@router.get("/events/{event_id}", response_model=EventOut)
def get_event(
    event_id: str,
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> EventOut:
    try:
        return EventOut.model_validate(service.get_event(db, event_id))
    except service.AgendaError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e


@router.patch("/events/{event_id}", response_model=EventOut)
def update_event(
    event_id: str,
    data: EventUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> EventOut:
    try:
        event = service.update_event(
            db, event_id=event_id, tenant_id=user.tenant_id, actor=user.user_id, data=data,
            by_ai=user.is_ai,
        )
    except service.AgendaError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return EventOut.model_validate(event)


@router.post("/events/{event_id}/cancel", response_model=EventOut)
def cancel_event(
    event_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> EventOut:
    try:
        event = service.cancel_event(
            db, event_id=event_id, tenant_id=user.tenant_id, actor=user.user_id,
            by_ai=user.is_ai,
        )
    except service.AgendaError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return EventOut.model_validate(event)


@router.post("/events/{event_id}/reschedule", response_model=CreateEventResult)
def reschedule_event(
    event_id: str,
    data: RescheduleRequest,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> CreateEventResult:
    try:
        event, conflicts = service.reschedule_event(
            db, event_id=event_id, tenant_id=user.tenant_id, actor=user.user_id,
            starts_at=data.starts_at, ends_at=data.ends_at, by_ai=user.is_ai,
        )
    except service.AgendaError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return CreateEventResult(
        event=EventOut.model_validate(event),
        conflicts=[EventOut.model_validate(c) for c in conflicts],
    )
