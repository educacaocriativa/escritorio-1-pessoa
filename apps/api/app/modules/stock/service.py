"""Controle de Estoque: itens, movimentações (ledger), alertas e baixa automática na venda."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit
from app.modules.stock.models import (
    REASON_SALE,
    StockItem,
    StockMovement,
)
from app.modules.stock.schemas import ItemCreate, ItemUpdate


class StockError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def create_item(db: Session, *, tenant_id: str, actor: str, data: ItemCreate) -> StockItem:
    item = StockItem(
        tenant_id=tenant_id,
        name=data.name,
        sku=data.sku,
        product_id=data.product_id,
        quantity=data.quantity,
        unit_cost_cents=data.unit_cost_cents,
        min_quantity=data.min_quantity,
        unit=data.unit,
    )
    db.add(item)
    db.flush()
    if data.quantity:
        db.add(StockMovement(
            tenant_id=tenant_id, item_id=item.id, delta=data.quantity,
            reason="purchase", note="Estoque inicial",
        ))
    audit.record(db, tenant_id=tenant_id, actor=actor, action="stock.item.create", target=item.id)
    db.commit()
    db.refresh(item)
    return item


def get_item(db: Session, item_id: str) -> StockItem:
    item = db.get(StockItem, item_id)
    if item is None:
        raise StockError("Item não encontrado", 404)
    return item


def list_items(db: Session, *, only_active: bool = False) -> list[StockItem]:
    stmt = select(StockItem).order_by(StockItem.name)
    if only_active:
        stmt = stmt.where(StockItem.active.is_(True))
    return list(db.scalars(stmt).all())


def update_item(
    db: Session, *, item_id: str, tenant_id: str, actor: str, data: ItemUpdate
) -> StockItem:
    item = get_item(db, item_id)
    for f in ("name", "sku", "product_id", "unit_cost_cents", "min_quantity", "unit", "active"):
        val = getattr(data, f)
        if val is not None:
            setattr(item, f, val)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="stock.item.update", target=item.id)
    db.commit()
    db.refresh(item)
    return item


def adjust(
    db: Session, *, item_id: str, tenant_id: str, actor: str, delta: int, reason: str, note: str
) -> StockItem:
    """Soma/subtrai quantidade e registra a movimentação. FOR UPDATE serializa ajustes."""
    if delta == 0:
        raise StockError("Informe uma quantidade diferente de zero", 422)
    item = db.scalar(select(StockItem).where(StockItem.id == item_id).with_for_update())
    if item is None:
        raise StockError("Item não encontrado", 404)
    new_qty = item.quantity + delta
    if new_qty < 0:
        raise StockError("Quantidade insuficiente em estoque", 409)
    item.quantity = new_qty
    db.add(StockMovement(
        tenant_id=tenant_id, item_id=item.id, delta=delta, reason=reason, note=note,
    ))
    audit.record(db, tenant_id=tenant_id, actor=actor, action="stock.adjust", target=item.id)
    db.commit()
    db.refresh(item)
    return item


def list_movements(db: Session, *, item_id: str) -> list[StockMovement]:
    stmt = (
        select(StockMovement)
        .where(StockMovement.item_id == item_id)
        .order_by(StockMovement.created_at.desc())
    )
    return list(db.scalars(stmt).all())


def low_stock(db: Session) -> list[StockItem]:
    stmt = (
        select(StockItem)
        .where(StockItem.active.is_(True), StockItem.quantity <= StockItem.min_quantity)
        .order_by(StockItem.quantity)
    )
    return list(db.scalars(stmt).all())


def summary(db: Session) -> dict:
    count = db.scalar(select(func.count(StockItem.id)).where(StockItem.active.is_(True))) or 0
    value = db.scalar(
        select(func.coalesce(func.sum(StockItem.quantity * StockItem.unit_cost_cents), 0))
        .where(StockItem.active.is_(True))
    ) or 0
    low = db.scalar(
        select(func.count(StockItem.id)).where(
            StockItem.active.is_(True), StockItem.quantity <= StockItem.min_quantity
        )
    ) or 0
    return {"item_count": count, "total_value_cents": value, "low_stock_count": low}


def consume_for_product(
    db: Session, *, tenant_id: str, product_id: str, qty: int, actor: str
) -> None:
    """Baixa automática na venda: se houver item ligado ao produto, subtrai (sem commit).

    Faz parte da MESMA transação da venda (products.sell commita). Não bloqueia a venda se
    faltar estoque — apenas registra (a quantidade pode ficar negativa para sinalizar ruptura).
    """
    item = db.scalar(
        select(StockItem)
        .where(StockItem.product_id == product_id, StockItem.active.is_(True))
        .with_for_update()
    )
    if item is None:
        return
    item.quantity -= qty
    db.add(StockMovement(
        tenant_id=tenant_id, item_id=item.id, delta=-qty, reason=REASON_SALE,
        note="Baixa automática por venda",
    ))
    audit.record(db, tenant_id=tenant_id, actor=actor, action="stock.sale", target=item.id)
