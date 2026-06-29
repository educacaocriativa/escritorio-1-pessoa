"""Rotas da Central de Orçamentos."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.crm.models import Client
from app.modules.quotes import service
from app.modules.quotes.models import Quote
from app.modules.quotes.schemas import (
    QuoteCreate,
    QuoteOut,
    QuotesSummary,
    QuoteUpdate,
    ScopeRequest,
    ScopeResult,
)

router = APIRouter(prefix="/quotes", tags=["quotes"])

_guard = require_module("quotes")


def _out(q: Quote, db: Session) -> QuoteOut:
    client = db.get(Client, q.client_id) if q.client_id else None
    return QuoteOut(
        id=q.id,
        tenant_id=q.tenant_id,
        client_id=q.client_id,
        client_name=client.name if client else None,
        title=q.title,
        items=q.items,
        discount_cents=q.discount_cents,
        subtotal_cents=q.subtotal_cents,
        total_cents=q.total_cents,
        status=q.status,
        valid_until=q.valid_until,
        notes=q.notes,
        charge_id=q.charge_id,
        created_at=q.created_at,
    )


def _err(e: service.QuoteError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/summary", response_model=QuotesSummary)
def summary(
    _u: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> QuotesSummary:
    return QuotesSummary(**service.summary(db))


@router.post("/scope", response_model=ScopeResult)
def scope(
    data: ScopeRequest,
    _u: CurrentUser = Depends(_guard),
    _db: Session = Depends(get_tenant_db),
) -> ScopeResult:
    return ScopeResult(description=service.generate_scope(data.brief))


@router.get("", response_model=list[QuoteOut])
def list_quotes(
    status: str | None = Query(default=None),
    _u: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[QuoteOut]:
    return [_out(q, db) for q in service.list_quotes(db, status=status)]


@router.post("", response_model=QuoteOut, status_code=201)
def create_quote(
    data: QuoteCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> QuoteOut:
    q = service.create_quote(db, tenant_id=user.tenant_id, actor=user.user_id, data=data)
    return _out(q, db)


@router.get("/{quote_id}", response_model=QuoteOut)
def get_quote(
    quote_id: str,
    _u: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> QuoteOut:
    try:
        return _out(service.get_quote(db, quote_id), db)
    except service.QuoteError as e:
        raise _err(e) from e


@router.patch("/{quote_id}", response_model=QuoteOut)
def update_quote(
    quote_id: str,
    data: QuoteUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> QuoteOut:
    try:
        q = service.update_quote(
            db, quote_id=quote_id, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
    except service.QuoteError as e:
        raise _err(e) from e
    return _out(q, db)


def _transition(fn, quote_id, user, db) -> QuoteOut:
    try:
        q = fn(db, quote_id=quote_id, tenant_id=user.tenant_id, actor=user.user_id)
    except service.QuoteError as e:
        raise _err(e) from e
    return _out(q, db)


@router.post("/{quote_id}/send", response_model=QuoteOut)
def send_quote(
    quote_id: str, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
):
    return _transition(service.send_quote, quote_id, user, db)


@router.post("/{quote_id}/approve", response_model=QuoteOut)
def approve_quote(
    quote_id: str, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
):
    return _transition(service.approve_quote, quote_id, user, db)


@router.post("/{quote_id}/reject", response_model=QuoteOut)
def reject_quote(
    quote_id: str, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
):
    return _transition(service.reject_quote, quote_id, user, db)
