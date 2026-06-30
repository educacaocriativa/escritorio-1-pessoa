"""Regras de Contas a Pagar: cadastro, baixa, vencimento na agenda, previsão de custos."""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit
from app.modules.agenda.models import (
    KIND_COBRANCA_PAGAR,
    PRIORITY_NORMAL,
    STATUS_DONE,
    STATUS_SCHEDULED,
    AgendaEvent,
)
from app.modules.payables.models import (
    STATUS_CANCELED,
    STATUS_OPEN,
    STATUS_PAID,
    Payable,
)
from app.modules.payables.schemas import PayableCreate


class PayableError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def is_overdue(p: Payable, today: date | None = None) -> bool:
    today = today or datetime.now(UTC).date()
    return p.status == STATUS_OPEN and p.due_date < today


def create_payable(db: Session, *, tenant_id: str, actor: str, data: PayableCreate) -> Payable:
    payable = Payable(
        tenant_id=tenant_id,
        description=data.description,
        category=data.category,
        supplier=data.supplier,
        amount_cents=data.amount_cents,
        due_date=data.due_date,
        recurrence=data.recurrence,
        payment_code=data.payment_code,
        attachment_url=data.attachment_url,
        status=STATUS_OPEN,
    )
    db.add(payable)
    db.flush()

    day_start = datetime.combine(data.due_date, time.min, tzinfo=UTC)
    event = AgendaEvent(
        tenant_id=tenant_id,
        title=f"A pagar: {data.supplier or data.description or 'conta'}",
        kind=KIND_COBRANCA_PAGAR,
        status=STATUS_SCHEDULED,
        priority=PRIORITY_NORMAL,
        source="payables",
        starts_at=day_start,
        ends_at=day_start.replace(hour=23, minute=59),
        all_day=True,
        amount_cents=data.amount_cents,
        external_ref=payable.id,
    )
    db.add(event)
    db.flush()
    payable.agenda_event_id = event.id

    audit.record(db, tenant_id=tenant_id, actor=actor, action="payable.create", target=payable.id)
    db.commit()
    db.refresh(payable)
    return payable


def get_payable(db: Session, payable_id: str) -> Payable:
    p = db.get(Payable, payable_id)
    if p is None:
        raise PayableError("Conta não encontrada", 404)
    return p


def update_payable(db: Session, *, payable_id: str, tenant_id: str, actor: str, data) -> Payable:
    """Atualiza o boleto/Pix recebido (código e/ou anexo) de uma conta."""
    p = get_payable(db, payable_id)
    if data.payment_code is not None:
        p.payment_code = data.payment_code
    if data.attachment_url is not None:
        p.attachment_url = data.attachment_url
    audit.record(db, tenant_id=tenant_id, actor=actor, action="payable.update", target=p.id)
    db.commit()
    db.refresh(p)
    return p


def list_payables(
    db: Session, *, status: str | None = None, limit: int = 200, offset: int = 0
) -> list[Payable]:
    limit = max(1, min(limit, 500))
    stmt = select(Payable).order_by(Payable.due_date)
    if status:
        stmt = stmt.where(Payable.status == status)
    return list(db.scalars(stmt.limit(limit).offset(max(0, offset))).all())


def mark_paid(db: Session, *, payable_id: str, tenant_id: str, actor: str) -> Payable:
    p = db.scalar(select(Payable).where(Payable.id == payable_id).with_for_update())
    if p is None:
        raise PayableError("Conta não encontrada", 404)
    if p.status == STATUS_PAID:
        return p
    if p.status == STATUS_CANCELED:
        raise PayableError("Conta cancelada não pode ser paga", 409)
    p.status = STATUS_PAID
    p.paid_at = datetime.now(UTC)
    if p.agenda_event_id:
        ev = db.get(AgendaEvent, p.agenda_event_id)
        if ev is not None:
            ev.status = STATUS_DONE  # não fica "atrasado" na agenda
    audit.record(db, tenant_id=tenant_id, actor=actor, action="payable.paid", target=p.id)
    db.commit()
    db.refresh(p)
    return p


def cancel_payable(db: Session, *, payable_id: str, tenant_id: str, actor: str) -> Payable:
    p = get_payable(db, payable_id)
    if p.status == STATUS_PAID:
        raise PayableError("Conta paga não pode ser cancelada", 409)
    p.status = STATUS_CANCELED
    audit.record(db, tenant_id=tenant_id, actor=actor, action="payable.cancel", target=p.id)
    db.commit()
    db.refresh(p)
    return p


def list_categories(db: Session) -> list[str]:
    rows = db.scalars(select(Payable.category).distinct().order_by(Payable.category)).all()
    return list(rows)


def summary(db: Session) -> dict:
    today = datetime.now(UTC).date()
    week_end = today + timedelta(days=7)
    month_start = today.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)

    open_rows = list(db.scalars(select(Payable).where(Payable.status == STATUS_OPEN)).all())
    overdue = [p for p in open_rows if p.due_date < today]
    open_future = [p for p in open_rows if p.due_date >= today]

    paid_month = db.scalar(
        select(func.coalesce(func.sum(Payable.amount_cents), 0)).where(
            Payable.status == STATUS_PAID,
            Payable.paid_at >= datetime.combine(month_start, time.min, tzinfo=UTC),
        )
    ) or 0
    month_total = db.scalar(
        select(func.coalesce(func.sum(Payable.amount_cents), 0)).where(
            Payable.status != STATUS_CANCELED,
            Payable.due_date >= month_start,
            Payable.due_date < next_month,
        )
    ) or 0

    return {
        "open_cents": sum(p.amount_cents for p in open_future),
        "overdue_cents": sum(p.amount_cents for p in overdue),
        "week_cents": sum(p.amount_cents for p in open_future if p.due_date < week_end),
        "month_cents": month_total,
        "paid_month_cents": paid_month,
    }


def monthly_costs(db: Session) -> int:
    """Custo do mês para o Cockpit: total de contas (não canceladas) com vencimento no mês."""
    today = datetime.now(UTC).date()
    month_start = today.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    return db.scalar(
        select(func.coalesce(func.sum(Payable.amount_cents), 0)).where(
            Payable.status != STATUS_CANCELED,
            Payable.due_date >= month_start,
            Payable.due_date < next_month,
        )
    ) or 0
