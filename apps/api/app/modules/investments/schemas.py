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
    # A conta bancária da aplicação (Onda 2b-i). Opcional na criação, obrigatória para lançar
    # rendimento — ver `service.ContaNaoVinculadaError`.
    bank_account_id: str | None = Field(default=None, max_length=36)

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
    # Onda 2b-i. `None` = não altera (o vínculo não é removível por aqui: desvincular reabriria o
    # termo P3 para os rendimentos futuros, e não existe caso de uso para isso).
    bank_account_id: str | None = Field(default=None, max_length=36)

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
    # Onda 2b-ii: CALCULADO dos movimentos da conta bancária vinculada, não mais a coluna.
    # `None` = inafirmável (sem vínculo, ou saldo de abertura declarado desconhecido — Story 8.21).
    # **`None` não é zero:** zero seria a afirmação "você não tem nada aplicado". Pode ser NEGATIVO
    # (resgate bruto que levou rendimento ainda não lançado junto) — e não é clampado.
    principal_cents: int | None
    accrued_yield_cents: int
    opened_at: date
    bank_account_id: str | None
    created_at: datetime


class RentabilityOut(BaseModel):
    account_id: str
    principal_cents: int | None  # Onda 2b-ii — ver InvestmentAccountOut
    accrued_yield_cents: int
    # Rentabilidade TOTAL (rendimento acumulado / principal). `None` quando o principal é `None`,
    # zero ou NEGATIVO — ver `service._pct`.
    total_rentability_pct: float | None
    # Rentabilidade do PERÍODO (soma dos rendimentos com competência no intervalo / principal).
    # Mesmas três condições de `None`. start/end None = período aberto (todo o histórico).
    period_rentability_pct: float | None
    period_yield_cents: int
    start: date | None
    end: date | None
