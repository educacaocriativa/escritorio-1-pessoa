"""Rotas da conta de investimento (rendimento, rentabilidade — Story 5.6)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.investments import service
from app.modules.investments.models import InvestmentAccount
from app.modules.investments.schemas import (
    InvestmentAccountCreate,
    InvestmentAccountOut,
    InvestmentAccountUpdate,
    RegisterYieldRequest,
    RentabilityOut,
)

router = APIRouter(prefix="/investments", tags=["investments"])

_guard = require_module("investments")


def _out(a: InvestmentAccount) -> InvestmentAccountOut:
    return InvestmentAccountOut(
        id=a.id,
        name=a.name,
        kind=a.kind,
        index_rate_label=a.index_rate_label,
        principal_cents=a.principal_cents,
        accrued_yield_cents=a.accrued_yield_cents,
        opened_at=a.opened_at,
        created_at=a.created_at,
    )


def _err(e: service.InvestmentError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


@router.get("", response_model=list[InvestmentAccountOut])
def list_accounts(
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[InvestmentAccountOut]:
    return [_out(a) for a in service.list_accounts(db)]


@router.post("", response_model=InvestmentAccountOut, status_code=201)
def create_account(
    data: InvestmentAccountCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> InvestmentAccountOut:
    acc = service.create_account(db, tenant_id=user.tenant_id, actor=user.user_id, data=data)
    return _out(acc)


@router.patch("/{account_id}", response_model=InvestmentAccountOut)
def update_account(
    account_id: str,
    data: InvestmentAccountUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> InvestmentAccountOut:
    try:
        acc = service.update_account(
            db, account_id=account_id, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
    except service.InvestmentError as e:
        raise _err(e) from e
    return _out(acc)


@router.post("/{account_id}/yield", response_model=InvestmentAccountOut)
def register_yield(
    account_id: str,
    data: RegisterYieldRequest,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> InvestmentAccountOut:
    try:
        acc = service.register_yield(
            db,
            account_id=account_id,
            tenant_id=user.tenant_id,
            actor=user.user_id,
            amount_cents=data.amount_cents,
            date=data.date,
            chart_account_id=data.chart_account_id,
        )
    except service.InvestmentError as e:
        raise _err(e) from e
    return _out(acc)


@router.get("/{account_id}/rentability", response_model=RentabilityOut)
def rentability(
    account_id: str,
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> RentabilityOut:
    try:
        result = service.rentability(db, account_id=account_id, start=start, end=end)
    except service.InvestmentError as e:
        raise _err(e) from e
    return RentabilityOut(**result)
