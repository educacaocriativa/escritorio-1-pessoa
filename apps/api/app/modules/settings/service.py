"""Configurações: perfil da empresa + Brand Kit (um por tenant, criado sob demanda)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.modules.auth.models import Tenant
from app.modules.settings.models import TenantProfile
from app.modules.settings.schemas import ProfileUpdate

_FIELDS = (
    "display_name", "document", "email", "phone", "address", "website", "about",
    "logo_url", "primary_color", "secondary_color", "accent_color", "text_color",
    "bg_color", "font", "timezone",
    "whatsapp_token", "whatsapp_phone_id", "whatsapp_waba_id",
)


def get_profile(db: Session, tenant_id: str) -> TenantProfile:
    """Retorna o perfil do tenant, criando com padrões na primeira vez."""
    profile = db.scalar(select(TenantProfile))
    if profile is None:
        tenant = db.get(Tenant, tenant_id)
        profile = TenantProfile(
            tenant_id=tenant_id,
            display_name=tenant.legal_name if tenant else "",
            document=tenant.document if tenant else "",
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def update_profile(
    db: Session, *, tenant_id: str, actor: str, data: ProfileUpdate
) -> TenantProfile:
    profile = get_profile(db, tenant_id)
    for f in _FIELDS:
        val = getattr(data, f)
        if val is not None:
            setattr(profile, f, val)
    # None no PATCH = "não altera"; "" desvincula (sem auto-enroll). Mesmo padrão de
    # contract_id/cost_center_id em receivables/service.py::update_charge.
    if data.default_entry_funnel_id is not None:
        profile.default_entry_funnel_id = data.default_entry_funnel_id or None
    audit.record(db, tenant_id=tenant_id, actor=actor, action="settings.profile.update",
                 target=profile.id)
    db.commit()
    db.refresh(profile)
    return profile
