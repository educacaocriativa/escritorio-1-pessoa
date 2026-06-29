"""Schemas do Super Admin (Master). Gerencia as contas (tenant + owner)."""
from __future__ import annotations

from pydantic import BaseModel

from app.modules.auth.schemas import RegisterRequest, TenantOut, UserOut


class CreateAccountRequest(RegisterRequest):
    """Mesma forma do registro — mas só o Master pode chamar (acesso pago)."""


class UpdateAccountRequest(BaseModel):
    name: str | None = None
    is_active: bool | None = None


class AccountOut(BaseModel):
    tenant: TenantOut
    owner: UserOut
