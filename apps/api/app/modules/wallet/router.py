"""Rotas da Carteira & Split."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.tenancy import (
    CurrentUser,
    get_tenant_db,
    require_module,
    require_platform_admin,
)
from app.db.session import get_db
from app.modules.wallet import service
from app.modules.wallet.schemas import (
    PayoutResult,
    PlatformEarningsSummary,
    SplitRates,
    TransactionCreate,
    TransactionOut,
    WalletSummary,
)

router = APIRouter(prefix="/wallet", tags=["wallet"])

_guard = require_module("wallet")


@router.get("/summary", response_model=WalletSummary)
def summary(
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> WalletSummary:
    return WalletSummary(**service.wallet_summary(db))


@router.get("/transactions", response_model=list[TransactionOut])
def list_transactions(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[TransactionOut]:
    txs = service.list_transactions(db, limit=limit, offset=offset)
    return [TransactionOut.model_validate(t) for t in txs]


@router.post("/transactions", response_model=TransactionOut, status_code=201)
def create_transaction(
    data: TransactionCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> TransactionOut:
    tx = service.create_transaction(
        db, tenant_id=user.tenant_id, actor=user.user_id, by_ai=user.is_ai, data=data
    )
    return TransactionOut.model_validate(tx)


@router.post("/transactions/{tx_id}/settle", response_model=TransactionOut)
def settle(
    tx_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> TransactionOut:
    try:
        tx = service.settle(db, tx_id=tx_id, tenant_id=user.tenant_id, actor=user.user_id)
    except service.WalletError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return TransactionOut.model_validate(tx)


@router.post("/payout", response_model=PayoutResult)
def payout(
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayoutResult:
    return PayoutResult(**service.request_payout(db, tenant_id=user.tenant_id, actor=user.user_id))


# ── Master: ganhos da plataforma ───────────────────────


@router.get("/platform-earnings", response_model=PlatformEarningsSummary, tags=["platform-admin"])
def platform_earnings(
    _admin: CurrentUser = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> PlatformEarningsSummary:
    return PlatformEarningsSummary(**service.platform_earnings(db))


@router.get("/split-rates", response_model=SplitRates, tags=["platform-admin"])
def get_split_rates(
    _admin: CurrentUser = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> SplitRates:
    return SplitRates(**service.current_rates(db))


@router.put("/split-rates", response_model=SplitRates, tags=["platform-admin"])
def update_split_rates(
    data: SplitRates,
    _admin: CurrentUser = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> SplitRates:
    try:
        rates = service.update_split_rates(
            db,
            product_pct=data.product_pct,
            service_pct=data.service_pct,
            recurring_pct=data.recurring_pct,
        )
    except service.WalletError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return SplitRates(**rates)
