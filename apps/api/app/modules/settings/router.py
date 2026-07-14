"""Rotas de Configurações + Brand Kit."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.settings import service
from app.modules.settings.models import TenantProfile
from app.modules.settings.schemas import ProfileOut, ProfileUpdate

router = APIRouter(prefix="/settings", tags=["settings"])

_guard = require_module("settings")


def _out(p: TenantProfile) -> ProfileOut:
    return ProfileOut(
        display_name=p.display_name, document=p.document, email=p.email, phone=p.phone,
        address=p.address, website=p.website, about=p.about, logo_url=p.logo_url,
        primary_color=p.primary_color, secondary_color=p.secondary_color,
        accent_color=p.accent_color, text_color=p.text_color, bg_color=p.bg_color, font=p.font,
        timezone=p.timezone, default_entry_funnel_id=p.default_entry_funnel_id,
    )


@router.get("/profile", response_model=ProfileOut)
def get_profile(
    user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> ProfileOut:
    return _out(service.get_profile(db, user.tenant_id))


@router.patch("/profile", response_model=ProfileOut)
def update_profile(
    data: ProfileUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ProfileOut:
    return _out(service.update_profile(db, tenant_id=user.tenant_id, actor=user.user_id, data=data))
