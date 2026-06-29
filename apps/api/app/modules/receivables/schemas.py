"""Schemas de Contas a Receber."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.modules.receivables.models import ALL_METHODS
from app.modules.wallet.models import ALL_KINDS


class ChargeCreate(BaseModel):
    client_id: str | None = None
    description: str = ""
    kind: str  # product/service/recurring (define o split quando paga)
    method: str
    amount_cents: int = Field(gt=0)
    due_date: date

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in ALL_KINDS:
            raise ValueError(f"kind inválido: {v}")
        return v

    @field_validator("method")
    @classmethod
    def _method(cls, v: str) -> str:
        if v not in ALL_METHODS:
            raise ValueError(f"method inválido: {v}")
        return v


class ChargeOut(BaseModel):
    id: str
    tenant_id: str
    client_id: str | None
    description: str
    kind: str
    method: str
    amount_cents: int
    due_date: date
    status: str
    is_overdue: bool
    payment_code: str
    transaction_id: str | None
    created_at: datetime


class ChargesSummary(BaseModel):
    open_cents: int  # em aberto (a vencer)
    overdue_cents: int  # vencido e não pago
    paid_cents: int  # recebido
    open_count: int
    overdue_count: int
