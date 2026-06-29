"""Schemas de Produtos, Cupons e Alunos."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.modules.products.models import ALL_DISCOUNTS, ALL_KINDS


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: str
    price_cents: int = Field(gt=0)
    description: str = ""
    stock: int | None = Field(default=None, ge=0)

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in ALL_KINDS:
            raise ValueError(f"kind inválido: {v}")
        return v


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    price_cents: int | None = Field(default=None, gt=0)
    description: str | None = None
    active: bool | None = None
    stock: int | None = Field(default=None, ge=0)


class ProductOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    kind: str
    price_cents: int
    description: str
    active: bool
    stock: int | None
    checkout_url: str
    students: int
    created_at: datetime


class CouponCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    discount_type: str
    discount_value: int = Field(gt=0)
    product_id: str | None = None
    max_uses: int | None = Field(default=None, gt=0)
    expires_at: date | None = None

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("discount_type")
    @classmethod
    def _type(cls, v: str) -> str:
        if v not in ALL_DISCOUNTS:
            raise ValueError(f"discount_type inválido: {v}")
        return v


class CouponOut(BaseModel):
    id: str
    tenant_id: str
    code: str
    discount_type: str
    discount_value: int
    product_id: str | None
    active: bool
    uses: int
    max_uses: int | None
    expires_at: date | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SellRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr | None = None
    method: str = "pix"
    coupon_code: str | None = None


class EnrollmentOut(BaseModel):
    id: str
    tenant_id: str
    product_id: str
    product_name: str | None
    name: str
    email: str | None
    status: str
    amount_cents: int
    created_at: datetime
