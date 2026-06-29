"""Rota do Cockpit — resumo do dia. Exige tenant autenticado (módulo 'cockpit')."""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.agenda.schemas import EventOut
from app.modules.cockpit import service
from app.modules.cockpit.schemas import (
    AgendaSummary,
    CockpitSummary,
    CrmSummary,
    FinanceSummary,
    OverdueCharge,
)

router = APIRouter(prefix="/cockpit", tags=["cockpit"])

_guard = require_module("cockpit")


@router.get("/summary", response_model=CockpitSummary)
def summary(
    day: date | None = Query(default=None, description="Dia (YYYY-MM-DD) interpretado em UTC."),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> CockpitSummary:
    # 'day' já é validado pelo FastAPI (date) — input malformado retorna 422 automaticamente.
    # A janela é ancorada na meia-noite UTC; o frontend (que conhece o fuso do usuário) deve
    # passar o 'day' correto. Limitação de fuso por tenant registrada no CLAUDE.md §6.1.
    base = day if day else datetime.now(UTC).date()
    day_start = datetime.combine(base, time.min, tzinfo=UTC)
    day_end = day_start + timedelta(days=1)

    today_count, today_events, upcoming = service.agenda_summary(
        db, day_start=day_start, day_end=day_end
    )
    crm = service.crm_summary(db)

    return CockpitSummary(
        agenda=AgendaSummary(
            today_count=today_count,
            today_events=[EventOut.model_validate(e) for e in today_events],
            upcoming_critical=[EventOut.model_validate(e) for e in upcoming],
        ),
        crm=CrmSummary(**crm),
        finance=FinanceSummary(**service.finance_summary(db)),
        overdue=[OverdueCharge(**o) for o in service.overdue_charges(db)],
    )
