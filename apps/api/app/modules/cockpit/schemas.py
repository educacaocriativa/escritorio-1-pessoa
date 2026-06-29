"""Schemas do Cockpit (dashboard de entrada). Agrega outros módulos — sem modelos próprios."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from app.modules.agenda.schemas import EventOut


class OverdueCharge(BaseModel):
    charge_id: str
    client_name: str
    description: str
    amount_cents: int
    due_date: date


class AgendaSummary(BaseModel):
    today_count: int
    today_events: list[EventOut]
    upcoming_critical: list[EventOut]  # prazos fatais etc. (tarja vermelha)


class StageCount(BaseModel):
    stage_id: str
    name: str
    count: int
    is_won: bool
    is_lost: bool


class CrmSummary(BaseModel):
    total_clients: int
    won_count: int
    lost_count: int
    conversion_rate: float  # won / total (0..1)
    by_stage: list[StageCount]


class FinanceSummary(BaseModel):
    """Placeholder até existirem os módulos financeiros (Fase 2)."""

    available: bool = False
    net_revenue_cents: int | None = None
    monthly_costs_cents: int | None = None
    signed_contracts: int | None = None


class CockpitSummary(BaseModel):
    agenda: AgendaSummary
    crm: CrmSummary
    finance: FinanceSummary
    overdue: list[OverdueCharge]  # cobranças em atraso (p/ cobrar com IA)
