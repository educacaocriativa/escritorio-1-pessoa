"""Configurações: perfil da empresa + Brand Kit (um por tenant, criado sob demanda)."""
from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.modules.auth.models import Tenant
from app.modules.settings.models import TenantProfile
from app.modules.settings.schemas import ProfileUpdate
from app.modules.whatsapp_inbox.models import PublicWhatsappAccount
from app.modules.whatsapp_templates.models import (
    PURPOSE_VARIABLE_SPECS,
    STATUS_APPROVED,
    WhatsappTemplate,
)


class SettingsError(Exception):
    """Erro de domínio do módulo de Configurações (mesmo padrão de FunnelError)."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def _validate_template_bindings(db: Session, bindings: dict[str, str]) -> None:
    """Cada propósito só pode ser vinculado a um template do PRÓPRIO tenant (RLS via db.get),
    já APROVADO pela Meta, e com exatamente a quantidade de variáveis que aquele propósito
    preenche (ver PURPOSE_VARIABLE_SPECS) — evita vincular um template com menos/mais
    variáveis do que o sistema vai passar em tempo de envio."""
    for purpose, template_id in bindings.items():
        if purpose not in PURPOSE_VARIABLE_SPECS:
            raise SettingsError(f"Propósito de WhatsApp desconhecido: {purpose}")
        if not template_id:
            continue  # "" desvincula esse propósito — nada a validar
        tpl = db.get(WhatsappTemplate, template_id)
        if tpl is None:
            raise SettingsError(f"Template não encontrado para o propósito '{purpose}'")
        if tpl.status != STATUS_APPROVED:
            raise SettingsError(
                f"O template vinculado a '{purpose}' ainda não foi aprovado pela Meta"
            )
        expected = len(PURPOSE_VARIABLE_SPECS[purpose])
        if tpl.variable_count != expected:
            labels = ", ".join(PURPOSE_VARIABLE_SPECS[purpose])
            raise SettingsError(
                f"O template para '{purpose}' precisa ter exatamente {expected} "
                f"variável(is) ({labels}), mas tem {tpl.variable_count}"
            )


_FIELDS = (
    "display_name", "document", "email", "phone", "address", "website", "about",
    "logo_url", "primary_color", "secondary_color", "accent_color", "text_color",
    "bg_color", "font", "timezone",
    "whatsapp_token", "whatsapp_phone_id", "whatsapp_waba_id", "whatsapp_app_secret",
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


def _sync_whatsapp_webhook_snapshot(db: Session, profile: TenantProfile) -> None:
    """Mantém `public_whatsapp_accounts` em sincronia com as credenciais do tenant — dual-write
    no mesmo espírito de `integration_keys`/`public_integration_keys`. Remove qualquer snapshot
    antigo do tenant (cobre o caso de `phone_id` ter mudado) e recria só se as 4 credenciais
    (token/phone_id/waba_id/app_secret) estiverem TODAS presentes. Gera `verify_token`
    automaticamente na primeira vez que isso acontece."""
    existing = db.scalars(
        select(PublicWhatsappAccount).where(
            PublicWhatsappAccount.tenant_id == profile.tenant_id
        )
    ).all()
    for row in existing:
        db.delete(row)

    fully_configured = bool(
        profile.whatsapp_token
        and profile.whatsapp_phone_id
        and profile.whatsapp_waba_id
        and profile.whatsapp_app_secret
    )
    if not fully_configured:
        profile.whatsapp_verify_token = None
        return

    if not profile.whatsapp_verify_token:
        profile.whatsapp_verify_token = secrets.token_urlsafe(24)

    db.add(
        PublicWhatsappAccount(
            phone_number_id=profile.whatsapp_phone_id,
            tenant_id=profile.tenant_id,
            app_secret=profile.whatsapp_app_secret,
            verify_token=profile.whatsapp_verify_token,
        )
    )


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
    if data.whatsapp_template_bindings is not None:
        _validate_template_bindings(db, data.whatsapp_template_bindings)
        profile.whatsapp_template_bindings = data.whatsapp_template_bindings
    _sync_whatsapp_webhook_snapshot(db, profile)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="settings.profile.update",
                 target=profile.id)
    db.commit()
    db.refresh(profile)
    return profile
