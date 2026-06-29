"""Rotas do Construtor de Funil de Vendas."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.funnels import service
from app.modules.funnels.models import Funnel
from app.modules.funnels.schemas import (
    ComponentCategory,
    FunnelCreate,
    FunnelOut,
    FunnelSummary,
    FunnelUpdate,
)

router = APIRouter(prefix="/funnels", tags=["funnels"])

_guard = require_module("funnels")


def _out(f: Funnel) -> FunnelOut:
    return FunnelOut(
        id=f.id, tenant_id=f.tenant_id, name=f.name, nodes=f.nodes, edges=f.edges,
        created_at=f.created_at,
    )


def _err(e: service.FunnelError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/components", response_model=list[ComponentCategory])
def components(_u: CurrentUser = Depends(_guard)) -> list[ComponentCategory]:
    return [ComponentCategory(**c) for c in service.CATALOG]


@router.get("", response_model=list[FunnelSummary])
def list_funnels(
    _u: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> list[FunnelSummary]:
    return [
        FunnelSummary(id=f.id, name=f.name, node_count=len(f.nodes), created_at=f.created_at)
        for f in service.list_funnels(db)
    ]


@router.post("", response_model=FunnelOut, status_code=201)
def create_funnel(
    data: FunnelCreate, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> FunnelOut:
    return _out(service.create_funnel(db, tenant_id=user.tenant_id, actor=user.user_id, data=data))


@router.get("/{funnel_id}", response_model=FunnelOut)
def get_funnel(
    funnel_id: str, _u: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> FunnelOut:
    try:
        return _out(service.get_funnel(db, funnel_id))
    except service.FunnelError as e:
        raise _err(e) from e


@router.patch("/{funnel_id}", response_model=FunnelOut)
def update_funnel(
    funnel_id: str,
    data: FunnelUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> FunnelOut:
    try:
        f = service.update_funnel(
            db, funnel_id=funnel_id, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
    except service.FunnelError as e:
        raise _err(e) from e
    return _out(f)


@router.delete("/{funnel_id}", status_code=204)
def delete_funnel(
    funnel_id: str, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> Response:
    try:
        service.delete_funnel(db, funnel_id=funnel_id, tenant_id=user.tenant_id, actor=user.user_id)
    except service.FunnelError as e:
        raise _err(e) from e
    return Response(status_code=204)
