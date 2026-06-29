"""Schemas Pydantic do módulo auth. Espelham packages/shared-types/src/index.ts."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$")
RESERVED_SLUGS = {
    "www", "api", "admin", "app", "mail", "e1p", "static", "cdn", "platform",
    "support", "billing", "auth", "status", "assets", "help", "blog",
}


class RegisterRequest(BaseModel):
    legal_name: str = Field(min_length=2, max_length=255)
    document: str = Field(min_length=11, max_length=18)  # CPF/CNPJ (só dígitos ou formatado)
    slug: str = Field(min_length=3, max_length=63)  # subdomínio: <slug>.e1p.com
    email: EmailStr
    name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("slug")
    @classmethod
    def valid_slug(cls, v: str) -> str:
        v = v.strip().lower()
        if not SLUG_RE.match(v):
            raise ValueError("slug inválido: use letras minúsculas, números e hífens")
        if v in RESERVED_SLUGS:
            raise ValueError("slug reservado")
        return v

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class TenantOut(BaseModel):
    id: str
    slug: str
    legal_name: str
    document: str
    created_at: datetime

    model_config = {"from_attributes": True}


class UserOut(BaseModel):
    id: str
    tenant_id: str
    email: str
    name: str
    role: Literal["owner", "sub_user"]
    allowed_modules: list[str]
    is_active: bool
    is_platform_admin: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionInfo(BaseModel):
    """Retorno de /auth/me — apenas identidade, SEM reemitir credencial."""

    user: UserOut
    tenant: TenantOut


class AuthToken(SessionInfo):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 (não é senha, é o tipo do token OAuth)
