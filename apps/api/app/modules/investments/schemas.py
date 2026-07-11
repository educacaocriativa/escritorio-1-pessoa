"""Schemas da conta de investimento (Story 5.6)."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


def _clean(v: str | None) -> str | None:
    if v is None:
        return None
    return v.strip()


class InvestmentAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="", max_length=24)  # tipo de aplicação (texto livre)
    index_rate_label: str = Field(default="", max_length=64)  # rótulo do indexador/taxa
    principal_cents: int = Field(default=0, ge=0)  # principal aplicado (centavos)
    opened_at: date

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("nome não pode ser vazio")
        return v

    @field_validator("kind", "index_rate_label")
    @classmethod
    def _text(cls, v: str) -> str:
        return v.strip()


class InvestmentAccountUpdate(BaseModel):
    # Editar principal/indexador/tipo/nome (Task 2). Todos opcionais (None = não altera).
    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: str | None = Field(default=None, max_length=24)
    index_rate_label: str | None = Field(default=None, max_length=64)
    principal_cents: int | None = Field(default=None, ge=0)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("nome não pode ser vazio")
        return v

    @field_validator("kind", "index_rate_label")
    @classmethod
    def _text(cls, v: str | None) -> str | None:
        return _clean(v)


class RegisterYieldRequest(BaseModel):
    """Registrar rendimento (juro) de uma aplicação num período (Task 2/3).

    `amount_cents` > 0 (rendimento positivo). `date` é a data de competência do lançamento (regime
    de competência — entra na DRE nesse período). `chart_account_id` (opcional) DEVE apontar a uma
    conta do grupo `FINANCEIRO` quando informado (422 caso contrário) — ver service.
    """
    amount_cents: int = Field(gt=0)
    date: date
    chart_account_id: str | None = None


class InvestmentAccountOut(BaseModel):
    id: str
    name: str
    kind: str
    index_rate_label: str
    principal_cents: int
    accrued_yield_cents: int
    opened_at: date
    created_at: datetime


class RentabilityOut(BaseModel):
    account_id: str
    principal_cents: int
    accrued_yield_cents: int
    # Rentabilidade TOTAL (rendimento acumulado / principal). None se principal == 0 (evita ÷0).
    total_rentability_pct: float | None
    # Rentabilidade do PERÍODO (soma dos rendimentos com competência no intervalo / principal).
    # None se principal == 0. start/end None = período aberto (todo o histórico).
    period_rentability_pct: float | None
    period_yield_cents: int
    start: date | None
    end: date | None
