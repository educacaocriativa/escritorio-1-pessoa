"""Rota do Cockpit — resumo do dia. Exige tenant autenticado (módulo 'cockpit')."""
from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.core.tz import day_window_utc
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
    day: date | None = Query(
        default=None, description="Dia (YYYY-MM-DD) interpretado no fuso do tenant."
    ),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> CockpitSummary:
    # 'day' já é validado pelo FastAPI (date) — input malformado retorna 422 automaticamente.
    # A janela do dia é ancorada na meia-noite do FUSO do tenant (convertida p/ UTC), corrigindo a
    # antiga dívida de "meia-noite UTC crua" (CLAUDE.md §Cockpit). Import lazy de settings para não
    # acoplar o Cockpit ao módulo settings (mesmo padrão da Agenda).
    from app.modules.settings.service import get_profile

    base = day if day else datetime.now(UTC).date()
    profile = get_profile(db, _user.tenant_id)
    day_start, day_end = day_window_utc(base, profile.timezone)

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
