"""Agregação do Cockpit — lê Agenda + CRM e monta o resumo do dia.

SOMENTE LEITURA: não escreve nada (não semeia estágios — isso é responsabilidade do módulo
CRM no seu próprio fluxo). Atravessa módulos por composição, mantendo a regra de cada domínio
no seu lugar.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.agenda import service as agenda_service
from app.modules.agenda.models import (
    PRIORITY_CRITICAL,
    STATUS_CANCELLED,
    STATUS_DONE,
    AgendaEvent,
)
from app.modules.crm.models import Client, PipelineStage

UPCOMING_CRITICAL_LIMIT = 10
TODAY_EVENTS_PREVIEW = 100


def agenda_summary(
    db: Session, *, day_start: datetime, day_end: datetime
) -> tuple[int, list[AgendaEvent], list[AgendaEvent]]:
    """(contagem real do dia, prévia dos eventos do dia, próximos críticos pendentes)."""
    today_count = agenda_service.count_events(db, start=day_start, end=day_end)

    preview = [
        e
        for e in agenda_service.list_events(
            db, start=day_start, end=day_end, limit=TODAY_EVENTS_PREVIEW
        )
        if e.status != STATUS_CANCELLED
    ]

    # Críticos pendentes (prazo fatal / tarja vermelha): exclui cancelados E concluídos —
    # não faz sentido alarmar sobre prazo já cumprido. Ancorado no dia visualizado.
    crit_stmt = (
        select(AgendaEvent)
        .where(
            AgendaEvent.priority == PRIORITY_CRITICAL,
            AgendaEvent.status.notin_([STATUS_CANCELLED, STATUS_DONE]),
            AgendaEvent.ends_at >= day_start,
        )
        .order_by(AgendaEvent.starts_at)
        .limit(UPCOMING_CRITICAL_LIMIT)
    )
    upcoming_critical = list(db.scalars(crit_stmt).all())
    return today_count, preview, upcoming_critical


def crm_summary(db: Session) -> dict:
    """Contagem por estágio + conversão (ganhos / total), via GROUP BY (não carrega clientes).

    NÃO semeia estágios: se o tenant ainda não tem funil, retorna resumo vazio.
    """
    stages = list(
        db.scalars(select(PipelineStage).order_by(PipelineStage.position, PipelineStage.id)).all()
    )
    rows = db.execute(
        select(Client.stage_id, func.count(Client.id)).group_by(Client.stage_id)
    ).all()
    counts: dict[str | None, int] = {stage_id: n for stage_id, n in rows}

    by_stage = []
    total = won = lost = 0
    for stage in stages:
        n = counts.get(stage.id, 0)
        total += n
        if stage.is_won:
            won += n
        if stage.is_lost:
            lost += n
        by_stage.append(
            {
                "stage_id": stage.id,
                "name": stage.name,
                "count": n,
                "is_won": stage.is_won,
                "is_lost": stage.is_lost,
            }
        )
    conversion = (won / total) if total else 0.0
    return {
        "total_clients": total,
        "won_count": won,
        "lost_count": lost,
        "conversion_rate": round(conversion, 4),
        "by_stage": by_stage,
    }
