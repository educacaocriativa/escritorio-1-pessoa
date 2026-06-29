"""Schemas da Central de Orçamentos."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class QuoteItem(BaseModel):
    description: str = Field(min_length=1, max_length=255)
    quantity: int = Field(gt=0)
    unit_price_cents: int = Field(ge=0)


class QuoteCreate(BaseModel):
    client_id: str | None = None
    title: str = Field(min_length=1, max_length=255)
    items: list[QuoteItem] = Field(min_length=1)
    discount_cents: int = Field(default=0, ge=0)
    valid_until: date | None = None
    notes: str = ""


class QuoteUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    items: list[QuoteItem] | None = None
    discount_cents: int | None = Field(default=None, ge=0)
    valid_until: date | None = None
    notes: str | None = None


class QuoteOut(BaseModel):
    id: str
    tenant_id: str
    client_id: str | None
    client_name: str | None
    title: str
    items: list[QuoteItem]
    discount_cents: int
    subtotal_cents: int
    total_cents: int
    status: str
    valid_until: date | None
    notes: str
    charge_id: str | None
    created_at: datetime


class QuotesSummary(BaseModel):
    draft_count: int
    sent_cents: int  # valor em orçamentos enviados (aguardando)
    approved_cents: int  # valor aprovado
    approved_count: int


class ScopeRequest(BaseModel):
    brief: str = Field(min_length=2, max_length=500)


class ScopeResult(BaseModel):
    description: str
