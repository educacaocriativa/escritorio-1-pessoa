"""Schemas da Carteira & Split."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.modules.wallet.models import ALL_KINDS, ALL_METHODS


class TransactionCreate(BaseModel):
    kind: str
    method: str
    gross_cents: int = Field(gt=0)
    description: str = ""
    client_id: str | None = None
    external_ref: str | None = None
    # Classificação DRE (Story 5.10, opcionais). competence_date omitida → service usa a data de
    # hoje como fallback (a transação já é caixa realizado, não tem due_date pra herdar).
    # chart_account_id/cost_center_id validados contra os cadastros do tenant se informados (404
    # se apontarem p/ registro inexistente/de outro tenant).
    competence_date: date | None = None
    chart_account_id: str | None = None
    cost_center_id: str | None = None

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


class TransactionOut(BaseModel):
    id: str
    tenant_id: str
    kind: str
    method: str
    description: str
    gross_cents: int
    platform_fee_cents: int
    net_cents: int
    status: str
    client_id: str | None
    external_ref: str | None
    competence_date: date | None
    chart_account_id: str | None
    cost_center_id: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class WalletSummary(BaseModel):
    available_cents: int  # disponível p/ saque
    pending_cents: int  # a receber (cartão a liberar)
    withdrawn_cents: int  # já sacado
    gross_total_cents: int  # bruto vendido (não estornado)
    fees_total_cents: int  # total retido pela plataforma


class PayoutResult(BaseModel):
    amount_cents: int
    transactions: int


class SplitRates(BaseModel):
    product_pct: int = Field(ge=0, le=95)
    service_pct: int = Field(ge=0, le=95)
    recurring_pct: int = Field(ge=0, le=95)


class PlatformEarningsSummary(BaseModel):
    """Visão do Master: ganhos da plataforma (GMV e taxas)."""

    gmv_cents: int  # volume total transacionado
    fees_cents: int  # total retido pela plataforma
    transaction_count: int
    by_kind: dict[str, int]  # taxa por tipo (product/service/recurring)
