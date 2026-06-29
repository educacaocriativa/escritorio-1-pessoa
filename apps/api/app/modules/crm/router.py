"""Rotas do CRM & Funil Kanban. Exigem tenant autenticado + permissão ao módulo 'crm'."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.crm import service
from app.modules.crm.schemas import (
    Board,
    BoardColumn,
    ClientCreate,
    ClientOut,
    ClientUpdate,
    MoveClientRequest,
    StageCreate,
    StageOut,
    StageUpdate,
)

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
    return Board(
        columns=[
            BoardColumn(
                stage=StageOut.model_validate(stage),
                clients=[ClientOut.model_validate(c) for c in clients],
            )
            for stage, clients in columns
        ]
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
