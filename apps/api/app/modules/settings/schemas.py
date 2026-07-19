"""Schemas de Configurações + Brand Kit."""
from __future__ import annotations

import re
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator

# Cor hex com `#`, 6 ou 8 dígitos (RRGGBB ou RRGGBBAA) — ambos cabem em String(9).
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")


class ProfileOut(BaseModel):
    display_name: str
    document: str
    email: str
    phone: str
    address: str
    website: str
    about: str
    logo_url: str
    primary_color: str
    secondary_color: str
    accent_color: str
    text_color: str
    bg_color: str
    font: str
    timezone: str
    # Funil de Vendas para auto-enroll de leads novos (source=landing/api). None = desligado.
    default_entry_funnel_id: str | None
    # WhatsApp Cloud API (Meta) — por tenant. `whatsapp_token` NUNCA é exposto aqui (só o boolean
    # de status); phone_id/waba_id não são segredos (IDs de conta), seguros para GET.
    whatsapp_configured: bool
    whatsapp_phone_id: str
    whatsapp_waba_id: str
    whatsapp_verify_token: str
    # Vínculo propósito→template (ver whatsapp_templates.models.PURPOSE_VARIABLE_SPECS).
    # Propósito ausente/vazio = esse fluxo do sistema ainda usa texto livre.
    whatsapp_template_bindings: dict[str, str]


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    document: str | None = Field(default=None, max_length=18)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=500)
    website: str | None = Field(default=None, max_length=255)
    about: str | None = None
    logo_url: str | None = Field(default=None, max_length=1024)
    primary_color: str | None = Field(default=None, max_length=9)
    secondary_color: str | None = Field(default=None, max_length=9)
    accent_color: str | None = Field(default=None, max_length=9)
    text_color: str | None = Field(default=None, max_length=9)
    bg_color: str | None = Field(default=None, max_length=9)
    font: str | None = Field(default=None, max_length=40)
    timezone: str | None = Field(default=None, max_length=64)
    # None = não altera; "" = desliga o auto-enroll (mesmo padrão de contract_id em Charge).
    default_entry_funnel_id: str | None = Field(default=None, max_length=36)
    # WhatsApp Cloud API (Meta) — por tenant. None = não altera; "" = limpa/desconecta.
    # Sem @field_validator: token/IDs são strings opacas vindas da Meta (não têm formato a validar
    # como as cores hex/URLs/timezone acima).
    whatsapp_token: str | None = Field(default=None)
    whatsapp_phone_id: str | None = Field(default=None, max_length=64)
    whatsapp_waba_id: str | None = Field(default=None, max_length=64)
    whatsapp_app_secret: str | None = Field(default=None)
    # None = não altera; um dict substitui o mapa INTEIRO (a UI sempre manda o mapa completo
    # após editar). Chave com valor "" desvincula aquele propósito específico.
    whatsapp_template_bindings: dict[str, str] | None = Field(default=None)

    # Validações de formato — só se aplicam a valores NÃO vazios.
    # None (omitido) = não altera; "" = limpar o campo (ambos preservados, AC4).

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, v: str | None) -> str | None:
        if not v:
            return v
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError("timezone inválido (não é um fuso IANA reconhecível)") from e
        return v

    @field_validator("logo_url")
    @classmethod
    def _validate_logo_url(cls, v: str | None) -> str | None:
        # logo_url aceita caminho relativo (ex.: "/api/public-images/{id}") — é o formato devolvido
        # pelo upload de imagem pública (uploadPublicImage.ts), que sempre passa pelo proxy /api.
        if not v or v.startswith("/"):
            return v
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(
                "URL inválida (http/https com host, ou caminho relativo iniciado por /)"
            )
        return v

    @field_validator("website")
    @classmethod
    def _validate_url(cls, v: str | None) -> str | None:
        if not v:
            return v
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("URL inválida (esquema http/https e host são obrigatórios)")
        return v

    @field_validator(
        "primary_color", "secondary_color", "accent_color", "text_color", "bg_color"
    )
    @classmethod
    def _validate_hex_color(cls, v: str | None) -> str | None:
        if not v:
            return v
        if not _HEX_COLOR_RE.match(v):
            raise ValueError("cor inválida (esperado hex #RRGGBB ou #RRGGBBAA)")
        return v
