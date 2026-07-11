"""Rotas do centro de custo (2ª dimensão de análise — Story 5.5)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.cost_centers import service
from app.modules.cost_centers.models import CostCenter
from app.modules.cost_centers.schemas import (
    CostCenterCreate,
    CostCenterOut,
    CostCenterUpdate,
)

router = APIRouter(prefix="/cost-centers", tags=["cost_centers"])

_guard = require_module("cost_centers")


def _out(c: CostCenter) -> CostCenterOut:
    return CostCenterOut(
        id=c.id,
        name=c.name,
        kind=c.kind,
        archived_at=c.archived_at,
        created_at=c.created_at,
    )


def _err(e: service.CostCenterError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


@router.get("", response_model=list[CostCenterOut])
def list_cost_centers(
    include_archived: bool = Query(default=False),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[CostCenterOut]:
    return [_out(c) for c in service.list_cost_centers(db, include_archived=include_archived)]


@router.post("", response_model=CostCenterOut, status_code=201)
def create_cost_center(
    data: CostCenterCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> CostCenterOut:
    try:
        cc = service.create_cost_center(
            db, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
    except service.CostCenterError as e:
        raise _err(e) from e
    return _out(cc)


@router.patch("/{cost_center_id}", response_model=CostCenterOut)
def update_cost_center(
    cost_center_id: str,
    data: CostCenterUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> CostCenterOut:
    try:
        cc = service.update_cost_center(
            db, cost_center_id=cost_center_id, tenant_id=user.tenant_id,
            actor=user.user_id, data=data,
        )
    except service.CostCenterError as e:
        raise _err(e) from e
    return _out(cc)


@router.post("/{cost_center_id}/archive", response_model=CostCenterOut)
def archive_cost_center(
    cost_center_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> CostCenterOut:
    try:
        cc = service.archive_cost_center(
            db, cost_center_id=cost_center_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.CostCenterError as e:
        raise _err(e) from e
    return _out(cc)
