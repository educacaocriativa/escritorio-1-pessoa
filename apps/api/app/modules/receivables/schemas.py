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
    recurrence: str = "none"  # none/weekly/monthly/yearly
    recurrence_count: int = Field(default=1, ge=1, le=60)

    @field_validator("recurrence")
    @classmethod
    def _recur(cls, v: str) -> str:
        if v not in {"none", "weekly", "monthly", "yearly"}:
            raise ValueError(f"recorrência inválida: {v}")
        return v

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
    client_name: str | None
    description: str
    kind: str
    method: str
    amount_cents: int
    due_date: date
    status: str
    is_overdue: bool
    protested_at: datetime | None
    recurrence: str
    recurrence_group: str | None
    payment_code: str
    transaction_id: str | None
    created_at: datetime


class RescheduleRequest(BaseModel):
    due_date: date


class ChargeUpdate(BaseModel):
    description: str | None = None
    amount_cents: int | None = Field(default=None, gt=0)
    due_date: date | None = None


class WebhookPayment(BaseModel):
    """Confirmação de pagamento vinda do gateway (Pix/cartão/boleto compensado)."""
    tenant_id: str
    charge_id: str
    status: str = "paid"
    secret: str = ""


class DunningResult(BaseModel):
    message: str
    status: str  # sent / logged / failed


class MessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class ChargesSummary(BaseModel):
    open_cents: int  # em aberto (a vencer)
    overdue_cents: int  # vencido e não pago
    paid_cents: int  # recebido
    open_count: int
    overdue_count: int
