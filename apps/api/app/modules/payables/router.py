"""Rotas de Contas a Pagar."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.payables import service
from app.modules.payables.models import Payable
from app.modules.payables.schemas import (
    PayableCreate,
    PayableOut,
    PayablesSummary,
    PayableUpdate,
    PaymentQueueOut,
)

router = APIRouter(prefix="/payables", tags=["payables"])

_guard = require_module("payables")


def _out(p: Payable) -> PayableOut:
    # Montagem canônica do PayableOut vive no service (reutilizada pela fila da Story 5.9).
    return service.payable_out(p)


def _err(e: service.PayableError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/summary", response_model=PayablesSummary)
def summary(
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayablesSummary:
    return PayablesSummary(**service.summary(db))


@router.get("/queue", response_model=PaymentQueueOut)
def payment_queue(
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PaymentQueueOut:
    """Story 5.9 — fila de pagamentos: Payables em aberto agrupados por janela de vencimento.
    Mesmo módulo/guard (`require_module('payables')`), sem autorização nova."""
    return service.payment_queue(db, tenant_id=user.tenant_id)


@router.get("/categories", response_model=list[str])
def categories(
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[str]:
    return service.list_categories(db)


@router.get("/bills", response_model=list[PayableOut])
def list_bills(
    status: str | None = Query(default=None),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[PayableOut]:
    return [_out(p) for p in service.list_payables(db, status=status)]


@router.get("/bills/{payable_id}", response_model=PayableOut)
def get_bill(
    payable_id: str,
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayableOut:
    try:
        return _out(service.get_payable(db, payable_id))
    except service.PayableError as e:
        raise _err(e) from e


@router.post("/bills", response_model=PayableOut, status_code=201)
def create_bill(
    data: PayableCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayableOut:
    try:
        p = service.create_payable(db, tenant_id=user.tenant_id, actor=user.user_id, data=data)
    except service.PayableError as e:
        raise _err(e) from e
    return _out(p)


@router.patch("/bills/{payable_id}", response_model=PayableOut)
def update_bill(
    payable_id: str,
    data: PayableUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayableOut:
    try:
        p = service.update_payable(
            db, payable_id=payable_id, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
    except service.PayableError as e:
        raise _err(e) from e
    return _out(p)


@router.post("/bills/{payable_id}/pay", response_model=PayableOut)
def pay_bill(
    payable_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayableOut:
    try:
        p = service.mark_paid(
            db, payable_id=payable_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.PayableError as e:
        raise _err(e) from e
    return _out(p)


@router.post("/bills/{payable_id}/cancel", response_model=PayableOut)
def cancel_bill(
    payable_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayableOut:
    try:
        p = service.cancel_payable(
            db, payable_id=payable_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.PayableError as e:
        raise _err(e) from e
    return _out(p)
