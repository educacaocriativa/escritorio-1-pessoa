"""Central de Orçamentos: totais, ciclo de status e efeito dominó (aprovar -> cobrança)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core import ai, audit, whatsapp
from app.modules.crm.models import Client
from app.modules.notifications.models import Notification
from app.modules.quotes.models import (
    STATUS_APPROVED,
    STATUS_DRAFT,
    STATUS_REJECTED,
    STATUS_SENT,
    Quote,
)
from app.modules.quotes.schemas import QuoteCreate, QuoteItem, QuoteUpdate
from app.modules.receivables import service as receivables_service
from app.modules.receivables.schemas import ChargeCreate

# prazo padrão da cobrança gerada ao aprovar
APPROVAL_DUE_DAYS = 7


class QuoteError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def compute_totals(items: list[QuoteItem], discount_cents: int) -> tuple[int, int]:
    subtotal = sum(i.quantity * i.unit_price_cents for i in items)
    total = max(0, subtotal - discount_cents)
    return subtotal, total


def create_quote(db: Session, *, tenant_id: str, actor: str, data: QuoteCreate) -> Quote:
    subtotal, total = compute_totals(data.items, data.discount_cents)
    quote = Quote(
        tenant_id=tenant_id,
        client_id=data.client_id,
        title=data.title,
        items=[i.model_dump() for i in data.items],
        discount_cents=data.discount_cents,
        subtotal_cents=subtotal,
        total_cents=total,
        valid_until=data.valid_until,
        notes=data.notes,
    )
    db.add(quote)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="quote.create", target=quote.id)
    db.commit()
    db.refresh(quote)
    return quote


def get_quote(db: Session, quote_id: str) -> Quote:
    q = db.get(Quote, quote_id)
    if q is None:
        raise QuoteError("Orçamento não encontrado", 404)
    return q


def list_quotes(db: Session, *, status: str | None = None) -> list[Quote]:
    stmt = select(Quote).order_by(Quote.created_at.desc())
    if status:
        stmt = stmt.where(Quote.status == status)
    return list(db.scalars(stmt).all())


def update_quote(
    db: Session, *, quote_id: str, tenant_id: str, actor: str, data: QuoteUpdate
) -> Quote:
    q = get_quote(db, quote_id)
    if q.status != STATUS_DRAFT:
        raise QuoteError("Só orçamentos em rascunho podem ser editados", 409)
    if data.title is not None:
        q.title = data.title
    if data.notes is not None:
        q.notes = data.notes
    if data.valid_until is not None:
        q.valid_until = data.valid_until
    if data.items is not None:
        q.items = [i.model_dump() for i in data.items]
    if data.discount_cents is not None:
        q.discount_cents = data.discount_cents
    if data.items is not None or data.discount_cents is not None:
        items = [QuoteItem(**i) for i in q.items]
        q.subtotal_cents, q.total_cents = compute_totals(items, q.discount_cents)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="quote.update", target=q.id)
    db.commit()
    db.refresh(q)
    return q


def send_quote(db: Session, *, quote_id: str, tenant_id: str, actor: str) -> Quote:
    """Marca como enviado e registra uma mensagem ao cliente (WhatsApp stub)."""
    q = get_quote(db, quote_id)
    if q.status not in (STATUS_DRAFT, STATUS_SENT):
        raise QuoteError("Orçamento já fechado", 409)
    client = db.get(Client, q.client_id) if q.client_id else None
    recipient = (client.phone if client and client.phone else None) or (
        client.name if client else "cliente"
    )
    valor = f"R$ {q.total_cents / 100:.2f}".replace(".", ",")
    msg = f"Olá! Segue seu orçamento de {q.title}: {valor}. Qualquer dúvida, estou à disposição!"
    status = whatsapp.send_text(to=recipient, text=msg)
    db.add(
        Notification(
            tenant_id=tenant_id, channel="whatsapp", recipient=recipient,
            client_id=q.client_id, message=msg, status=status,
        )
    )
    q.status = STATUS_SENT
    audit.record(db, tenant_id=tenant_id, actor=actor, action="quote.send", target=q.id)
    db.commit()
    db.refresh(q)
    return q


def approve_quote(db: Session, *, quote_id: str, tenant_id: str, actor: str) -> Quote:
    """Efeito dominó: aprova e GERA a cobrança (Contas a Receber) para o total.

    Atômico: a cobrança é construída SEM commit e gravada junto com a aprovação num único
    commit. FOR UPDATE serializa aprovações concorrentes (sem isso, duas gerariam 2 cobranças).
    """
    q = db.scalar(select(Quote).where(Quote.id == quote_id).with_for_update())
    if q is None:
        raise QuoteError("Orçamento não encontrado", 404)
    if q.status == STATUS_APPROVED:
        return q
    if q.status == STATUS_REJECTED:
        raise QuoteError("Orçamento recusado não pode ser aprovado", 409)
    if q.total_cents <= 0:
        raise QuoteError("Orçamento sem valor a cobrar não pode ser aprovado", 409)

    charge = receivables_service.build_charge(
        db,
        tenant_id=tenant_id,
        actor=actor,
        data=ChargeCreate(
            client_id=q.client_id,
            description=f"Orçamento aprovado: {q.title}",
            kind="service",
            method="pix",
            amount_cents=q.total_cents,
            due_date=(datetime.now(UTC).date() + timedelta(days=APPROVAL_DUE_DAYS)),
        ),
    )
    q.status = STATUS_APPROVED
    q.charge_id = charge.id
    audit.record(db, tenant_id=tenant_id, actor=actor, action="quote.approve", target=q.id)
    db.commit()
    db.refresh(q)
    return q


def reject_quote(db: Session, *, quote_id: str, tenant_id: str, actor: str) -> Quote:
    q = get_quote(db, quote_id)
    if q.status == STATUS_APPROVED:
        raise QuoteError("Orçamento aprovado não pode ser recusado", 409)
    q.status = STATUS_REJECTED
    audit.record(db, tenant_id=tenant_id, actor=actor, action="quote.reject", target=q.id)
    db.commit()
    db.refresh(q)
    return q


def summary(db: Session) -> dict:
    draft = db.scalar(select(func.count(Quote.id)).where(Quote.status == STATUS_DRAFT)) or 0
    sent = db.scalar(
        select(func.coalesce(func.sum(Quote.total_cents), 0)).where(Quote.status == STATUS_SENT)
    ) or 0
    approved = db.scalar(
        select(func.coalesce(func.sum(Quote.total_cents), 0)).where(Quote.status == STATUS_APPROVED)
    ) or 0
    approved_count = db.scalar(
        select(func.count(Quote.id)).where(Quote.status == STATUS_APPROVED)
    ) or 0
    return {
        "draft_count": draft,
        "sent_cents": sent,
        "approved_cents": approved,
        "approved_count": approved_count,
    }


def generate_scope(brief: str) -> str:
    """IA redige a descrição comercial do escopo (fallback p/ o próprio briefing)."""
    if not settings.anthropic_api_key:
        return brief.strip()
    system = (
        "Você é um redator comercial brasileiro. A partir do briefing, escreva UMA descrição "
        "de escopo profissional e enxuta (1-2 frases) para um orçamento. Responda só com o texto."
    )
    try:
        return ai.complete(system=system, user_message=brief, max_tokens=300).text.strip()
    except Exception:
        return brief.strip()
