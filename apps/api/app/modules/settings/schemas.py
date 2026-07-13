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
