"""Rotas da Central de Orçamentos (privadas) + visão pública da proposta (sem login)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.db.session import get_db, get_tenant_session_factory
from app.modules.quotes import service
from app.modules.quotes.models import Quote
from app.modules.quotes.schemas import (
    PublicAccept,
    PublicProposal,
    QuoteCreate,
    QuoteOut,
    QuotesSummary,
    QuoteUpdate,
    ScopeRequest,
    ScopeResult,
)

router = APIRouter(prefix="/quotes", tags=["quotes"])
public_router = APIRouter(prefix="/public/proposals", tags=["quotes-public"])

_guard = require_module("quotes")


def _out(q: Quote) -> QuoteOut:
    return QuoteOut(
        id=q.id,
        tenant_id=q.tenant_id,
        client_id=q.client_id,
        client_name=q.client_name,
        client_whatsapp=q.client_whatsapp,
        title=q.title,
        items=q.items,
        discount_cents=q.discount_cents,
        subtotal_cents=q.subtotal_cents,
        total_cents=q.total_cents,
        status=q.status,
        valid_until=q.valid_until,
        notes=q.notes,
        payment_terms=q.payment_terms,
        has_password=bool(q.link_password_hash),
        show_gallery=q.show_gallery,
        gallery=q.gallery,
        show_schedule=q.show_schedule,
        schedule=q.schedule,
        show_contract=q.show_contract,
        contract_text=q.contract_text,
        logo_url=q.logo_url,
        primary_color=q.primary_color,
        bg_color=q.bg_color,
        text_color=q.text_color,
        accent_color=q.accent_color,
        public_slug=q.public_slug,
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
    client_id: str | None = Query(default=None),
    _u: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[QuoteOut]:
    return [_out(q) for q in service.list_quotes(db, status=status, client_id=client_id)]


@router.post("", response_model=QuoteOut, status_code=201)
def create_quote(
    data: QuoteCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> QuoteOut:
    return _out(service.create_quote(db, tenant_id=user.tenant_id, actor=user.user_id, data=data))


@router.get("/{quote_id}", response_model=QuoteOut)
def get_quote(
    quote_id: str,
    _u: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> QuoteOut:
    try:
        return _out(service.get_quote(db, quote_id))
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
    return _out(q)


def _transition(fn, quote_id, user, db) -> QuoteOut:
    try:
        q = fn(db, quote_id=quote_id, tenant_id=user.tenant_id, actor=user.user_id)
    except service.QuoteError as e:
        raise _err(e) from e
    return _out(q)


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


# ── Público (sem login; lê o snapshot global) ───────────────────────────────
@public_router.get("/{slug}", response_model=PublicProposal)
def public_view(
    slug: str, password: str | None = Query(default=None), db: Session = Depends(get_db)
) -> PublicProposal:
    """Uso LEGÍTIMO de `get_db` (sem tenant): rota pública lê `published_proposals`, um snapshot
    GLOBAL sem RLS. NÃO toca `users` nem tabelas de negócio por tenant — seguro por design
    (guarda explícita exigida pela Story 1.2, AC1)."""
    try:
        return PublicProposal(**service.public_view(db, slug=slug, password=password))
    except service.QuoteError as e:
        raise _err(e) from e


@public_router.post("/{slug}/accept")
def public_accept(
    slug: str,
    data: PublicAccept,
    db: Session = Depends(get_db),
    session_factory=Depends(get_tenant_session_factory),
) -> dict:
    try:
        status = service.public_accept(
            db, slug=slug, password=data.password, session_factory=session_factory
        )
    except service.QuoteError as e:
        raise _err(e) from e
    return {"status": status}
