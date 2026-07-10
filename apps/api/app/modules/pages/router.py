"""Rotas do construtor de páginas (privadas) + página pública (sem login)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.db.session import get_db, get_tenant_session_factory
from app.modules.pages import service
from app.modules.pages.models import Page
from app.modules.pages.schemas import (
    LeadSubmit,
    PageCreate,
    PageOut,
    PageSummary,
    PageUpdate,
    PublicPage,
)

router = APIRouter(prefix="/pages", tags=["pages"])
public_router = APIRouter(prefix="/public/pages", tags=["pages-public"])

_guard = require_module("pages")


def _out(p: Page) -> PageOut:
    return PageOut(
        id=p.id,
        tenant_id=p.tenant_id,
        title=p.title,
        model=p.model,
        blocks=p.blocks,
        status=p.status,
        public_slug=p.public_slug,
        primary_color=p.primary_color,
        bg_color=p.bg_color,
        text_color=p.text_color,
        accent_color=p.accent_color,
        font=p.font,
        logo_url=p.logo_url,
        created_at=p.created_at,
    )


def _err(e: service.PageError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


@router.get("", response_model=list[PageSummary])
def list_pages(_u: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)):
    return [
        PageSummary(
            id=p.id,
            title=p.title,
            model=p.model,
            status=p.status,
            public_slug=p.public_slug,
            created_at=p.created_at,
        )
        for p in service.list_pages(db)
    ]


@router.post("", response_model=PageOut, status_code=201)
def create_page(
    data: PageCreate, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> PageOut:
    return _out(service.create_page(db, tenant_id=user.tenant_id, actor=user.user_id, data=data))


@router.get("/{page_id}", response_model=PageOut)
def get_page(page_id: str, _u: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)):
    try:
        return _out(service.get_page(db, page_id))
    except service.PageError as e:
        raise _err(e) from e


@router.patch("/{page_id}", response_model=PageOut)
def update_page(
    page_id: str,
    data: PageUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PageOut:
    try:
        p = service.update_page(
            db, page_id=page_id, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
    except service.PageError as e:
        raise _err(e) from e
    return _out(p)


def _transition(fn, page_id, user, db):
    try:
        return _out(fn(db, page_id=page_id, tenant_id=user.tenant_id, actor=user.user_id))
    except service.PageError as e:
        raise _err(e) from e


@router.post("/{page_id}/publish", response_model=PageOut)
def publish(
    page_id: str, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
):
    return _transition(service.publish, page_id, user, db)


@router.post("/{page_id}/unpublish", response_model=PageOut)
def unpublish(
    page_id: str, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
):
    return _transition(service.unpublish, page_id, user, db)


@router.delete("/{page_id}", status_code=204)
def delete_page(
    page_id: str, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> Response:
    try:
        service.delete_page(db, page_id=page_id, tenant_id=user.tenant_id, actor=user.user_id)
    except service.PageError as e:
        raise _err(e) from e
    return Response(status_code=204)


# ── Público (sem login) ─────────────────────────────────────────────────────
@public_router.get("/{slug}", response_model=PublicPage)
def public_view(slug: str, db: Session = Depends(get_db)) -> PublicPage:
    """Uso LEGÍTIMO de `get_db` (sem tenant): rota pública lê `published_pages`, um snapshot
    GLOBAL sem RLS. NÃO toca `users` nem tabelas de negócio por tenant — seguro por design
    (guarda explícita exigida pela Story 1.2, AC1)."""
    try:
        return PublicPage(**service.public_view(db, slug=slug))
    except service.PageError as e:
        raise _err(e) from e


@public_router.post("/{slug}/submit")
def public_submit(
    slug: str,
    data: LeadSubmit,
    db: Session = Depends(get_db),
    session_factory=Depends(get_tenant_session_factory),
) -> dict:
    try:
        service.public_submit(
            db,
            slug=slug,
            name=data.name,
            email=str(data.email) if data.email else None,
            phone=data.phone,
            session_factory=session_factory,
        )
    except service.PageError as e:
        raise _err(e) from e
    return {"status": "ok"}
