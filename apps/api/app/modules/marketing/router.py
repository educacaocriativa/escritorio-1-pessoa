"""Rotas do gerador de carrossel (Marketing)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.marketing import service
from app.modules.marketing.models import Carousel
from app.modules.marketing.schemas import (
    CarouselCreate,
    CarouselOut,
    CarouselUpdate,
    GenerateRequest,
    GenerateResult,
    TemplatePreset,
)

router = APIRouter(prefix="/marketing/carousels", tags=["marketing"])

_guard = require_module("marketing")


def _out(c: Carousel) -> CarouselOut:
    return CarouselOut(
        id=c.id,
        tenant_id=c.tenant_id,
        topic=c.topic,
        platform=c.platform,
        slides=c.slides,
        status=c.status,
        template=c.template,
        primary_color=c.primary_color,
        bg_color=c.bg_color,
        text_color=c.text_color,
        accent_color=c.accent_color,
        font=c.font,
        created_at=c.created_at,
    )


def _err(e: service.MarketingError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/templates", response_model=list[TemplatePreset])
def list_templates(_u: CurrentUser = Depends(_guard)) -> list[TemplatePreset]:
    return [TemplatePreset(**t) for t in service.TEMPLATES]


@router.post("/generate", response_model=GenerateResult)
def generate(
    data: GenerateRequest,
    _u: CurrentUser = Depends(_guard),
    _db: Session = Depends(get_tenant_db),
) -> GenerateResult:
    return GenerateResult(slides=service.generate_slides(data.topic, data.slides, data.tone))


@router.get("", response_model=list[CarouselOut])
def list_carousels(
    _u: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> list[CarouselOut]:
    return [_out(c) for c in service.list_carousels(db)]


@router.post("", response_model=CarouselOut, status_code=201)
def create_carousel(
    data: CarouselCreate, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> CarouselOut:
    car = service.create_carousel(db, tenant_id=user.tenant_id, actor=user.user_id, data=data)
    return _out(car)


@router.get("/{carousel_id}", response_model=CarouselOut)
def get_carousel(
    carousel_id: str, _u: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> CarouselOut:
    try:
        return _out(service.get_carousel(db, carousel_id))
    except service.MarketingError as e:
        raise _err(e) from e


@router.patch("/{carousel_id}", response_model=CarouselOut)
def update_carousel(
    carousel_id: str,
    data: CarouselUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> CarouselOut:
    try:
        c = service.update_carousel(
            db, carousel_id=carousel_id, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
    except service.MarketingError as e:
        raise _err(e) from e
    return _out(c)


@router.delete("/{carousel_id}", status_code=204)
def delete_carousel(
    carousel_id: str, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> Response:
    try:
        service.delete_carousel(
            db, carousel_id=carousel_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.MarketingError as e:
        raise _err(e) from e
    return Response(status_code=204)
