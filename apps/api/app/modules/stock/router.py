"""Rotas do Controle de Estoque."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.stock import service
from app.modules.stock.models import StockItem, StockMovement
from app.modules.stock.schemas import (
    AdjustRequest,
    ItemCreate,
    ItemOut,
    ItemUpdate,
    MovementOut,
    StockSummary,
)

router = APIRouter(prefix="/stock", tags=["stock"])

_guard = require_module("stock")


def _out(i: StockItem) -> ItemOut:
    return ItemOut(
        id=i.id,
        tenant_id=i.tenant_id,
        name=i.name,
        sku=i.sku,
        product_id=i.product_id,
        quantity=i.quantity,
        unit_cost_cents=i.unit_cost_cents,
        min_quantity=i.min_quantity,
        unit=i.unit,
        active=i.active,
        low=i.quantity <= i.min_quantity,
        value_cents=i.quantity * i.unit_cost_cents,
        created_at=i.created_at,
    )


def _mov(m: StockMovement) -> MovementOut:
    return MovementOut(
        id=m.id,
        item_id=m.item_id,
        delta=m.delta,
        reason=m.reason,
        note=m.note,
        created_at=m.created_at,
    )


def _err(e: service.StockError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/summary", response_model=StockSummary)
def summary(
    _u: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> StockSummary:
    return StockSummary(**service.summary(db))


@router.get("/low", response_model=list[ItemOut])
def low_stock(
    _u: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> list[ItemOut]:
    return [_out(i) for i in service.low_stock(db)]


@router.get("/items", response_model=list[ItemOut])
def list_items(
    only_active: bool = Query(default=False),
    _u: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[ItemOut]:
    return [_out(i) for i in service.list_items(db, only_active=only_active)]


@router.post("/items", response_model=ItemOut, status_code=201)
def create_item(
    data: ItemCreate, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> ItemOut:
    return _out(service.create_item(db, tenant_id=user.tenant_id, actor=user.user_id, data=data))


@router.get("/items/{item_id}", response_model=ItemOut)
def get_item(
    item_id: str, _u: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> ItemOut:
    try:
        return _out(service.get_item(db, item_id))
    except service.StockError as e:
        raise _err(e) from e


@router.patch("/items/{item_id}", response_model=ItemOut)
def update_item(
    item_id: str,
    data: ItemUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ItemOut:
    try:
        item = service.update_item(
            db, item_id=item_id, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
    except service.StockError as e:
        raise _err(e) from e
    return _out(item)


@router.post("/items/{item_id}/adjust", response_model=ItemOut)
def adjust(
    item_id: str,
    data: AdjustRequest,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ItemOut:
    try:
        item = service.adjust(
            db,
            item_id=item_id,
            tenant_id=user.tenant_id,
            actor=user.user_id,
            delta=data.delta,
            reason=data.valid_reason(),
            note=data.note,
        )
    except service.StockError as e:
        raise _err(e) from e
    return _out(item)


@router.get("/items/{item_id}/movements", response_model=list[MovementOut])
def movements(
    item_id: str, _u: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> list[MovementOut]:
    return [_mov(m) for m in service.list_movements(db, item_id=item_id)]
