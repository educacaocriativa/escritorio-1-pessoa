"""Rotas de Contas a Receber."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.receivables import service
from app.modules.receivables.models import Charge
from app.modules.receivables.schemas import (
    ChargeCreate,
    ChargeOut,
    ChargesSummary,
    DunningResult,
)

router = APIRouter(prefix="/receivables", tags=["receivables"])

_guard = require_module("receivables")


def _out(charge: Charge) -> ChargeOut:
    return ChargeOut(
        id=charge.id,
        tenant_id=charge.tenant_id,
        client_id=charge.client_id,
        description=charge.description,
        kind=charge.kind,
        method=charge.method,
        amount_cents=charge.amount_cents,
        due_date=charge.due_date,
        status=charge.status,
        is_overdue=service.is_overdue(charge),
        payment_code=charge.payment_code,
        transaction_id=charge.transaction_id,
        created_at=charge.created_at,
    )


def _err(e: service.ReceivableError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/summary", response_model=ChargesSummary)
def summary(
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ChargesSummary:
    return ChargesSummary(**service.summary(db))


@router.get("/charges", response_model=list[ChargeOut])
def list_charges(
    status: str | None = Query(default=None),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[ChargeOut]:
    return [_out(c) for c in service.list_charges(db, status=status)]


@router.post("/charges", response_model=ChargeOut, status_code=201)
def create_charge(
    data: ChargeCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ChargeOut:
    charge = service.create_charge(db, tenant_id=user.tenant_id, actor=user.user_id, data=data)
    return _out(charge)


@router.post("/charges/{charge_id}/pay", response_model=ChargeOut)
def pay_charge(
    charge_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ChargeOut:
    try:
        charge = service.mark_paid(
            db, charge_id=charge_id, tenant_id=user.tenant_id, actor=user.user_id, by_ai=user.is_ai
        )
    except service.ReceivableError as e:
        raise _err(e) from e
    return _out(charge)


@router.post("/charges/{charge_id}/collect", response_model=DunningResult)
def collect_charge(
    charge_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> DunningResult:
    """A IA escreve e envia uma cobrança amigável ao cliente no WhatsApp."""
    try:
        result = service.collect_with_ai(
            db, charge_id=charge_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.ReceivableError as e:
        raise _err(e) from e
    return DunningResult(**result)


@router.post("/charges/{charge_id}/cancel", response_model=ChargeOut)
def cancel_charge(
    charge_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ChargeOut:
    try:
        charge = service.cancel_charge(
            db, charge_id=charge_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.ReceivableError as e:
        raise _err(e) from e
    return _out(charge)
