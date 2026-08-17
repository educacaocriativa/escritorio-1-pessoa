"""Rotas do CRM & Funil Kanban. Exigem tenant autenticado + permissão ao módulo 'crm'."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.facts import CRM_NOTA_CRIADA
from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.agenda import service as agenda_service
from app.modules.agenda.models import AgendaEvent
from app.modules.crm import service, timeline
from app.modules.crm.models import Client
from app.modules.crm.schemas import (
    Board,
    BoardClient,
    BoardColumn,
    ClientCreate,
    ClientOut,
    ClientTimelineEntry,
    ClientTimelineOut,
    ClientUpdate,
    MoveClientRequest,
    NoteCreate,
    StageCreate,
    StageOut,
    StageUpdate,
)
from app.modules.whatsapp_inbox import service as inbox_service

router = APIRouter(prefix="/crm", tags=["crm"])

_guard = require_module("crm")


def _err(e: service.CrmError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


# ── Board ──────────────────────────────────────────────


@router.get("/board", response_model=Board)
def get_board(
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> Board:
    columns = service.build_board(db, user.tenant_id)
    ultimo = service.last_interaction_map(db)
    # Consulta agregada, uma para o board inteiro — o custo não cresce com a quantidade de
    # cards. Lida do módulo DONO da regra de "não lida" em vez de reimplementada aqui.
    esperando = inbox_service.unread_client_ids(db)
    # Idem: uma consulta agregada para o board inteiro, dona da Agenda. Devolve o EVENTO
    # inteiro (não uma tupla achatada) — aqui só extraímos `starts_at`/`title`, mas o mesmo
    # mapa também alimenta o bloco da ficha 360°, que lê outros campos do mesmo agregado.
    proximo = agenda_service.next_event_map(db)
    return Board(
        columns=[
            BoardColumn(
                stage=StageOut.model_validate(stage),
                clients=[_board_client(c, ultimo, esperando, proximo) for c in clients],
            )
            for stage, clients in columns
        ]
    )


def _board_client(
    c: Client,
    ultimo: dict[str, datetime],
    esperando: set[str],
    proximo: dict[str, AgendaEvent],
) -> BoardClient:
    # Statement, não expressão dentro do comprehension de propósito: um walrus lendo `ev` em
    # dois kwargs vizinhos só funciona hoje porque kwargs são avaliados na ordem em que estão
    # escritos — trocar `next_event_at`/`next_event_title` de lugar, ou inserir um campo entre
    # eles, não erra em lugar nenhum: silenciosamente lê o `ev` do card ANTERIOR do loop.
    # Isolando a consulta ao mapa numa variável antes de montar o objeto, essa armadilha não
    # existe — não "arrume" isto de volta para um walrus inline.
    ev = proximo.get(c.id)
    return BoardClient(
        **ClientOut.model_validate(c).model_dump(),
        last_interaction_at=ultimo.get(c.id),
        unread=c.id in esperando,
        next_event_at=ev.starts_at if ev else None,
        next_event_title=ev.title if ev else None,
    )


# ── Estágios ───────────────────────────────────────────


@router.get("/stages", response_model=list[StageOut])
def list_stages(
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[StageOut]:
    return [StageOut.model_validate(s) for s in service.ensure_stages(db, user.tenant_id)]


@router.post("/stages", response_model=StageOut, status_code=201)
def create_stage(
    data: StageCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> StageOut:
    try:
        stage = service.create_stage(db, tenant_id=user.tenant_id, actor=user.user_id, data=data)
    except service.CrmError as e:
        raise _err(e) from e
    return StageOut.model_validate(stage)


@router.patch("/stages/{stage_id}", response_model=StageOut)
def update_stage(
    stage_id: str,
    data: StageUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> StageOut:
    try:
        stage = service.update_stage(
            db, stage_id=stage_id, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
    except service.CrmError as e:
        raise _err(e) from e
    return StageOut.model_validate(stage)


@router.post("/stages/{stage_id}/archive", status_code=204)
def archive_stage(
    stage_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> Response:
    try:
        service.archive_stage(db, stage_id=stage_id, tenant_id=user.tenant_id, actor=user.user_id)
    except service.CrmError as e:
        raise _err(e) from e
    return Response(status_code=204)


@router.delete("/stages/{stage_id}", status_code=204)
def delete_stage(
    stage_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> Response:
    try:
        service.delete_stage(db, stage_id=stage_id, tenant_id=user.tenant_id, actor=user.user_id)
    except service.CrmError as e:
        raise _err(e) from e
    return Response(status_code=204)


# ── Clientes ───────────────────────────────────────────


@router.post("/clients", response_model=ClientOut, status_code=201)
def create_client(
    data: ClientCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ClientOut:
    try:
        client = service.create_client(
            db, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
    except service.CrmError as e:
        raise _err(e) from e
    return ClientOut.model_validate(client)


@router.get("/clients", response_model=list[ClientOut])
def list_clients(
    stage_id: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    gender: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[ClientOut]:
    clients = service.list_clients(
        db, stage_id=stage_id, tag=tag, gender=gender, search=search, limit=limit, offset=offset
    )
    return [ClientOut.model_validate(c) for c in clients]


@router.get("/clients/{client_id}", response_model=ClientOut)
def get_client(
    client_id: str,
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ClientOut:
    try:
        return ClientOut.model_validate(service.get_client(db, client_id))
    except service.CrmError as e:
        raise _err(e) from e


@router.patch("/clients/{client_id}", response_model=ClientOut)
def update_client(
    client_id: str,
    data: ClientUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ClientOut:
    try:
        client = service.update_client(
            db, client_id=client_id, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
    except service.CrmError as e:
        raise _err(e) from e
    return ClientOut.model_validate(client)


# ── Linha do tempo ─────────────────────────────────────


@router.get("/clients/{client_id}/timeline", response_model=ClientTimelineOut)
def get_timeline(
    client_id: str,
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ClientTimelineOut:
    try:
        service.get_client(db, client_id)  # 404 fail-closed antes de montar qualquer coisa
    except service.CrmError as e:
        raise _err(e) from e
    entries, truncated = timeline.build(db, client_id=client_id)
    return ClientTimelineOut(
        entries=[ClientTimelineEntry(**e) for e in entries], truncated=truncated
    )


@router.post("/clients/{client_id}/notes", response_model=ClientTimelineEntry, status_code=201)
def create_note(
    client_id: str,
    data: NoteCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ClientTimelineEntry:
    try:
        service.get_client(db, client_id)
    except service.CrmError as e:
        raise _err(e) from e
    event = service.record_event(
        db, tenant_id=user.tenant_id, client_id=client_id, kind=CRM_NOTA_CRIADA,
        title=data.title, body=data.body, actor=user.user_id, is_ai=user.is_ai,
    )
    db.commit()
    db.refresh(event)
    return ClientTimelineEntry(
        id=event.id, kind=event.kind, title=event.title, body=event.body,
        actor=event.actor, is_ai=event.is_ai, at=event.created_at,
    )


@router.post("/clients/{client_id}/move", response_model=ClientOut)
def move_client(
    client_id: str,
    data: MoveClientRequest,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ClientOut:
    try:
        client = service.move_client(
            db, client_id=client_id, tenant_id=user.tenant_id, actor=user.user_id,
            by_ai=user.is_ai, stage_id=data.stage_id,
        )
    except service.CrmError as e:
        raise _err(e) from e
    return ClientOut.model_validate(client)
