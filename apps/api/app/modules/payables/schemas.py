"""Schemas de Contas a Pagar."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.modules.payables.models import ALL_RECURRENCES, RECUR_NONE


class PayableCreate(BaseModel):
    description: str = ""
    category: str = "Geral"
    supplier: str = ""
    amount_cents: int = Field(gt=0)
    due_date: date
    recurrence: str = RECUR_NONE
    recurrence_count: int = Field(default=1, ge=1, le=60)  # quantas vezes repete
    payment_code: str = ""  # linha digitável do boleto OU Pix copia-e-cola
    attachment_url: str = Field(default="", max_length=1024)  # URL do boleto anexado

    @field_validator("recurrence")
    @classmethod
    def _recur(cls, v: str) -> str:
        if v not in ALL_RECURRENCES:
            raise ValueError(f"recorrência inválida: {v}")
        return v


class PayableUpdate(BaseModel):
    description: str | None = None
    category: str | None = None
    supplier: str | None = None
    amount_cents: int | None = Field(default=None, gt=0)
    due_date: date | None = None
    recurrence: str | None = None
    payment_code: str | None = None
    attachment_url: str | None = Field(default=None, max_length=1024)

    @field_validator("recurrence")
    @classmethod
    def _recur(cls, v: str | None) -> str | None:
        if v is not None and v not in ALL_RECURRENCES:
            raise ValueError(f"recorrência inválida: {v}")
        return v


class PayableOut(BaseModel):
    id: str
    tenant_id: str
    description: str
    category: str
    supplier: str
    amount_cents: int
    due_date: date
    status: str
    is_overdue: bool
    paid_at: datetime | None
    recurrence: str
    recurrence_count: int
    recurrence_group: str | None
    payment_code: str
    attachment_url: str
    created_at: datetime


class PayablesSummary(BaseModel):
    open_cents: int  # a pagar (a vencer)
    overdue_cents: int  # vencido e não pago
    week_cents: int  # vence nesta semana
    month_cents: int  # total do mês (não cancelado)
    paid_month_cents: int  # já pago no mês
