"""Schemas do Controle de Estoque."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.stock.models import ALL_REASONS


class ItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    sku: str = Field(default="", max_length=64)
    product_id: str | None = None
    quantity: int = Field(default=0, ge=0)
    unit_cost_cents: int = Field(default=0, ge=0)
    min_quantity: int = Field(default=0, ge=0)
    unit: str = Field(default="un", max_length=12)


class ItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    sku: str | None = Field(default=None, max_length=64)
    product_id: str | None = None
    unit_cost_cents: int | None = Field(default=None, ge=0)
    min_quantity: int | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=12)
    active: bool | None = None


class ItemOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    sku: str
    product_id: str | None
    quantity: int
    unit_cost_cents: int
    min_quantity: int
    unit: str
    active: bool
    low: bool  # quantity <= min_quantity
    value_cents: int  # quantity * unit_cost_cents
    created_at: datetime


class AdjustRequest(BaseModel):
    delta: int = Field(description="quantidade a somar (+) ou subtrair (-)")
    reason: str = "adjust"
    note: str = ""

    def valid_reason(self) -> str:
        return self.reason if self.reason in ALL_REASONS else "adjust"


class MovementOut(BaseModel):
    id: str
    item_id: str
    delta: int
    reason: str
    note: str
    created_at: datetime


class StockSummary(BaseModel):
    item_count: int
    total_value_cents: int
    low_stock_count: int
