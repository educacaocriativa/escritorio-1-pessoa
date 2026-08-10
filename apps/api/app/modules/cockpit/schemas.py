"""Schemas do Cockpit (dashboard de entrada). Agrega outros módulos — sem modelos próprios."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from app.core.money_planes import ORIGEM_INDISPONIVEL
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
    """Faturamento (plano 1) + custos + **saldo em conta** (plano 3) — nunca somados.

    ⚠️ **`net_revenue_cents` NÃO tem `_origem`, e a ausência é deliberada.** A Regra dos Planos
    §1.3c exige procedência em todo campo de **saldo**; faturamento não é saldo, e o design-mãe
    §6.5 diz explicitamente que aquele número está correto e não muda. Pendurar procedência nele
    aplicaria a regra fora do alvo — e transformaria um invariante mecânico em ritual.
    """

    available: bool = False
    net_revenue_cents: int | None = None
    monthly_costs_cents: int | None = None
    signed_contracts: int | None = None
    # Plano 3 (banco). `None` = nenhuma conta cadastrada — **não zero**: zero afirmaria "não há
    # nada no banco", que é falso e indistinguível de um saldo genuinamente zerado. O recorte é o
    # de `TOTAL_EM_CONTAS_LABEL` (todas as contas ativas, aplicação incluída), e a tela **nunca**
    # o soma com o faturamento num card único (§1.3c, §6.5).
    saldo_em_conta_cents: int | None = None
    saldo_em_conta_origem: str = ORIGEM_INDISPONIVEL


class CockpitSummary(BaseModel):
    agenda: AgendaSummary
    crm: CrmSummary
    finance: FinanceSummary
    overdue: list[OverdueCharge]  # cobranças em atraso (p/ cobrar com IA)
