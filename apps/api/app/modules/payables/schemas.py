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

    @field_validator("recurrence")
    @classmethod
    def _recur(cls, v: str) -> str:
        if v not in ALL_RECURRENCES:
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
    created_at: datetime


class PayablesSummary(BaseModel):
    open_cents: int  # a pagar (a vencer)
    overdue_cents: int  # vencido e não pago
    week_cents: int  # vence nesta semana
    month_cents: int  # total do mês (não cancelado)
    paid_month_cents: int  # já pago no mês
