"""Central de Orçamentos: construtor de proposta, totais, status, efeito dominó e link público."""
from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core import ai, audit, whatsapp
from app.core.security import hash_password, verify_password
from app.modules.crm.models import Client
from app.modules.notifications.models import Notification
from app.modules.quotes.models import (
    STATUS_APPROVED,
    STATUS_DRAFT,
    STATUS_REJECTED,
    STATUS_SENT,
    PublishedProposal,
    Quote,
)
from app.modules.quotes.schemas import QuoteCreate, QuoteItem, QuoteUpdate
from app.modules.receivables import service as receivables_service
from app.modules.receivables.schemas import ChargeCreate

# prazo padrão da cobrança gerada ao aprovar
APPROVAL_DUE_DAYS = 7

# campos "espelho" do construtor: nomes idênticos no schema e no modelo
_BUILDER_FIELDS = (
    "client_name", "client_whatsapp", "payment_terms",
    "show_gallery", "show_schedule", "show_contract", "contract_text",
    "logo_url", "primary_color", "bg_color", "text_color", "accent_color",
)
_JSON_FIELDS = ("gallery", "schedule")  # listas de pydantic -> dicts


class QuoteError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def compute_totals(items: list[QuoteItem], discount_cents: int) -> tuple[int, int]:
    subtotal = sum(i.quantity * i.unit_price_cents for i in items)
    total = max(0, subtotal - discount_cents)
    return subtotal, total


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:40] or "proposta").strip("-")


def _gen_slug(title: str) -> str:
    # sufixo aleatório longo: o link público não deve ser adivinhável a partir do título
    return f"{_slugify(title)}-{secrets.token_urlsafe(12)}"


def _snapshot_data(quote: Quote) -> dict:
    """Dados de EXIBIÇÃO para o link público (sem segredos)."""
    return {
        "title": quote.title,
        "client_name": quote.client_name,
        "items": quote.items,
        "subtotal_cents": quote.subtotal_cents,
        "discount_cents": quote.discount_cents,
        "total_cents": quote.total_cents,
        "payment_terms": quote.payment_terms,
        "show_gallery": quote.show_gallery,
        "gallery": quote.gallery,
        "show_schedule": quote.show_schedule,
        "schedule": quote.schedule,
        "show_contract": quote.show_contract,
        "contract_text": quote.contract_text,
        "logo_url": quote.logo_url,
        "primary_color": quote.primary_color,
        "bg_color": quote.bg_color,
        "text_color": quote.text_color,
        "accent_color": quote.accent_color,
        "status": quote.status,
        "valid_until": quote.valid_until.isoformat() if quote.valid_until else None,
    }


def _publish(db: Session, quote: Quote) -> None:
    """Upsert do snapshot público (tabela GLOBAL sem RLS)."""
    if not quote.public_slug:
        return
    snap = db.get(PublishedProposal, quote.public_slug)
    if snap is None:
        snap = PublishedProposal(slug=quote.public_slug)
        db.add(snap)
    snap.tenant_id = quote.tenant_id
    snap.quote_id = quote.id
    snap.password_hash = quote.link_password_hash
    snap.data = _snapshot_data(quote)


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
        gallery=[g.model_dump() for g in data.gallery],
        schedule=[s.model_dump() for s in data.schedule],
        public_slug=_gen_slug(data.title),
        **{f: getattr(data, f) for f in _BUILDER_FIELDS},
    )
    if data.link_password:
        quote.link_password_hash = hash_password(data.link_password)
    db.add(quote)
    db.flush()  # popula id
    _publish(db, quote)
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

    simple = ("title", "client_id", "valid_until", "notes", *_BUILDER_FIELDS)
    for field in simple:
        val = getattr(data, field)
        if val is not None:
            setattr(q, field, val)
    for field in _JSON_FIELDS:
        val = getattr(data, field)
        if val is not None:
            setattr(q, field, [x.model_dump() for x in val])
    if data.items is not None:
        q.items = [i.model_dump() for i in data.items]
    if data.discount_cents is not None:
        q.discount_cents = data.discount_cents
    if data.items is not None or data.discount_cents is not None:
        items = [QuoteItem(**i) for i in q.items]
        q.subtotal_cents, q.total_cents = compute_totals(items, q.discount_cents)
    if data.link_password is not None:  # "" remove a senha
        q.link_password_hash = hash_password(data.link_password) if data.link_password else None

    _publish(db, q)
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
    recipient = (
        q.client_whatsapp
        or (client.phone if client and client.phone else None)
        or q.client_name
        or (client.name if client else "cliente")
    )
    valor = f"R$ {q.total_cents / 100:.2f}".replace(".", ",")
    link = f"{settings.frontend_url.rstrip('/')}/orcamento/{q.public_slug}" if q.public_slug else ""
    msg = f"Olá! Segue sua proposta de {q.title}: {valor}. Veja em: {link}".strip()
    status = whatsapp.send_text(to=recipient, text=msg)
    db.add(
        Notification(
            tenant_id=tenant_id, channel="whatsapp", recipient=recipient,
            client_id=q.client_id, message=msg, status=status,
        )
    )
    q.status = STATUS_SENT
    _publish(db, q)
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
    # Efeito dominó completo: se o orçamento tem a aba "Contrato" ativada, gera o contrato
    # no MESMO commit (sem commitar lá dentro), atômico com a cobrança.
    if q.show_contract:
        from app.modules.contracts import service as contracts_service

        contracts_service.build_contract_from_quote(
            db, tenant_id=tenant_id, actor=actor, quote=q
        )
    _publish(db, q)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="quote.approve", target=q.id)
    db.commit()
    db.refresh(q)
    return q


def reject_quote(db: Session, *, quote_id: str, tenant_id: str, actor: str) -> Quote:
    q = get_quote(db, quote_id)
    if q.status == STATUS_APPROVED:
        raise QuoteError("Orçamento aprovado não pode ser recusado", 409)
    q.status = STATUS_REJECTED
    _publish(db, q)
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


# ── Link público (cliente abre sem login; lê da tabela GLOBAL) ──────────────
def _check_password(snap: PublishedProposal, password: str | None) -> None:
    if snap.password_hash and not (password and verify_password(password, snap.password_hash)):
        raise QuoteError("Senha incorreta ou ausente", 401)


def public_view(db: Session, *, slug: str, password: str | None) -> dict:
    snap = db.get(PublishedProposal, slug)
    if snap is None:
        raise QuoteError("Proposta não encontrada", 404)
    _check_password(snap, password)
    return snap.data


def public_accept(db: Session, *, slug: str, password: str | None, session_factory) -> str:
    """Aceite pelo cliente -> aprova o orçamento (efeito dominó) no contexto do tenant.

    `session_factory(tenant_id)` é o context manager `tenant_session` (injetado), para que a
    aprovação rode com a RLS do tenant dono da proposta — sem depender do token de ninguém.
    """
    snap = db.get(PublishedProposal, slug)
    if snap is None:
        raise QuoteError("Proposta não encontrada", 404)
    _check_password(snap, password)
    with session_factory(snap.tenant_id) as tdb:
        approve_quote(tdb, quote_id=snap.quote_id, tenant_id=snap.tenant_id, actor="cliente:link")
    return "approved"
