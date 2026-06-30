"""Regras de Contas a Receber: criar cobrança, baixa (→ carteira), resumo de inadimplência.

Integra com a Carteira (baixa cria Transaction com split) e com a Agenda (vencimento vira evento).
Tudo numa única transação por operação.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core import ai, audit, whatsapp
from app.core.recurrence import advance, occurrences
from app.db.base import _uuid
from app.modules.agenda.models import (
    KIND_COBRANCA_RECEBER,
    PRIORITY_NORMAL,
    STATUS_DONE,
    STATUS_SCHEDULED,
    AgendaEvent,
)
from app.modules.crm.models import Client
from app.modules.notifications.models import Notification
from app.modules.receivables.models import (
    STATUS_CANCELED,
    STATUS_OPEN,
    STATUS_PAID,
    Charge,
)
from app.modules.receivables.schemas import ChargeCreate
from app.modules.wallet import service as wallet_service


class ReceivableError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _payment_code(method: str, charge_id: str) -> str:
    """Stub do gateway (sem integração real ainda). Substituir por Asaas/Mercado Pago."""
    if method == "pix":
        return f"00020126-PIX-COPIA-E-COLA-{charge_id}"
    if method == "boleto":
        return f"34191.79001 01043.510047 91020.150008 1 0000{charge_id[:8]}"
    return f"https://pay.e1p.com/c/{charge_id}"  # link de cartão


def is_overdue(charge: Charge, today: date | None = None) -> bool:
    today = today or datetime.now(UTC).date()
    return charge.status == STATUS_OPEN and charge.due_date < today


def build_charge(db: Session, *, tenant_id: str, actor: str, data: ChargeCreate) -> Charge:
    """Cria a cobrança + evento de agenda na sessão SEM commitar.

    Permite que outros módulos (ex.: Orçamentos ao aprovar) gerem a cobrança atomicamente
    junto com sua própria mutação, num único commit.
    """
    charge = Charge(
        tenant_id=tenant_id,
        client_id=data.client_id,
        description=data.description,
        kind=data.kind,
        method=data.method,
        amount_cents=data.amount_cents,
        due_date=data.due_date,
        status=STATUS_OPEN,
    )
    db.add(charge)
    db.flush()  # popula charge.id (default aplicado no flush)
    charge.payment_code = _payment_code(data.method, charge.id)

    # Nome do cliente/empresa no título do evento (cai p/ a descrição se não houver cliente).
    client = db.get(Client, data.client_id) if data.client_id else None
    who = client.name if client else (data.description or "cobrança")

    # Injeta o vencimento na Agenda (marcador, não ocupa horário).
    day_start = datetime.combine(data.due_date, time.min, tzinfo=UTC)
    event = AgendaEvent(
        tenant_id=tenant_id,
        title=f"A receber: {who}",
        kind=KIND_COBRANCA_RECEBER,
        status=STATUS_SCHEDULED,
        priority=PRIORITY_NORMAL,
        source="receivables",
        starts_at=day_start,
        ends_at=day_start.replace(hour=23, minute=59),
        all_day=True,
        amount_cents=data.amount_cents,
        external_ref=charge.id,
    )
    db.add(event)
    db.flush()  # popula event.id
    charge.agenda_event_id = event.id

    # Boleto: já gera o arquivo (PDF) e anexa à cobrança, com o vencimento certo.
    if data.method == "boleto":
        _attach_boleto(db, tenant_id=tenant_id, charge=charge)

    audit.record(db, tenant_id=tenant_id, actor=actor, action="receivable.create", target=charge.id)
    return charge


def _attach_boleto(db: Session, *, tenant_id: str, charge: Charge) -> None:
    from app.core.boleto import generate_boleto_pdf
    from app.modules.attachments.models import Attachment
    from app.modules.auth.models import Tenant

    tenant = db.get(Tenant, tenant_id)
    client = db.get(Client, charge.client_id) if charge.client_id else None
    pdf = generate_boleto_pdf(
        payee=tenant.legal_name if tenant else "",
        payer=client.name if client else (charge.description or "Cliente"),
        amount_cents=charge.amount_cents,
        due_date=charge.due_date,
        code=charge.payment_code,
    )
    db.add(Attachment(
        tenant_id=tenant_id, owner_type="charge", owner_id=charge.id, label="boleto",
        filename=f"boleto-{charge.id[:8]}.pdf", content_type="application/pdf",
        size=len(pdf), data=pdf,
    ))


def create_charge(db: Session, *, tenant_id: str, actor: str, data: ChargeCreate) -> Charge:
    """Cria a cobrança. Se recorrente, gera N cobranças (uma por vencimento), cada uma com seu
    código e seu evento na Agenda — assim cada repetição recebe seu próprio boleto."""
    n = occurrences(data.recurrence, data.recurrence_count)
    group = _uuid() if n > 1 else None
    first: Charge | None = None
    for i in range(n):
        occ = data.model_copy(update={"due_date": advance(data.due_date, data.recurrence, i)})
        charge = build_charge(db, tenant_id=tenant_id, actor=actor, data=occ)
        charge.recurrence = data.recurrence
        charge.recurrence_count = n
        charge.recurrence_group = group
        if i == 0:
            first = charge
    db.commit()
    db.refresh(first)
    return first


def get_charge(db: Session, charge_id: str) -> Charge:
    charge = db.get(Charge, charge_id)
    if charge is None:
        raise ReceivableError("Cobrança não encontrada", 404)
    return charge


def list_charges(
    db: Session,
    *,
    status: str | None = None,
    client_id: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[Charge]:
    limit = max(1, min(limit, 500))
    stmt = select(Charge).order_by(Charge.due_date)
    if status:
        stmt = stmt.where(Charge.status == status)
    if client_id:
        stmt = stmt.where(Charge.client_id == client_id)
    return list(db.scalars(stmt.limit(limit).offset(max(0, offset))).all())


def reschedule_charge(
    db: Session, *, charge_id: str, tenant_id: str, actor: str, due_date: date
) -> Charge:
    """Troca o vencimento de uma cobrança em aberto e move o evento da agenda junto."""
    charge = get_charge(db, charge_id)
    if charge.status != STATUS_OPEN:
        raise ReceivableError("Só cobranças em aberto podem ter o vencimento alterado", 409)
    charge.due_date = due_date
    if charge.agenda_event_id:
        ev = db.get(AgendaEvent, charge.agenda_event_id)
        if ev is not None:
            day_start = datetime.combine(due_date, time.min, tzinfo=UTC)
            ev.starts_at = day_start
            ev.ends_at = day_start.replace(hour=23, minute=59)
            ev.status = STATUS_SCHEDULED  # volta a "agendado" (deixa de ficar vermelho se atrasara)
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="receivable.reschedule", target=charge.id
    )
    db.commit()
    db.refresh(charge)
    return charge


def update_charge(db: Session, *, charge_id: str, tenant_id: str, actor: str, data) -> Charge:
    """Edita a cobrança (descrição/valor/vencimento) em aberto e reverbera no evento da Agenda."""
    charge = get_charge(db, charge_id)
    if charge.status != STATUS_OPEN:
        raise ReceivableError("Só cobranças em aberto podem ser editadas", 409)
    if data.description is not None:
        charge.description = data.description
    if data.amount_cents is not None:
        charge.amount_cents = data.amount_cents
    if data.due_date is not None:
        charge.due_date = data.due_date

    ev = db.get(AgendaEvent, charge.agenda_event_id) if charge.agenda_event_id else None
    if ev is not None:
        if data.due_date is not None:
            day_start = datetime.combine(charge.due_date, time.min, tzinfo=UTC)
            ev.starts_at = day_start
            ev.ends_at = day_start.replace(hour=23, minute=59)
            ev.status = STATUS_SCHEDULED
        if data.amount_cents is not None:
            ev.amount_cents = charge.amount_cents
        if data.description is not None:
            client = db.get(Client, charge.client_id) if charge.client_id else None
            who = client.name if client else (charge.description or "cobrança")
            ev.title = f"A receber: {who}"

    audit.record(db, tenant_id=tenant_id, actor=actor, action="receivable.update", target=charge.id)
    db.commit()
    db.refresh(charge)
    return charge


def protest_charge(db: Session, *, charge_id: str, tenant_id: str, actor: str) -> Charge:
    """Protesta uma cobrança VENCIDA e em aberto (registra o protesto; cartório real é dívida)."""
    charge = get_charge(db, charge_id)
    if charge.status != STATUS_OPEN:
        raise ReceivableError("Só cobranças em aberto podem ser protestadas", 409)
    if not is_overdue(charge):
        raise ReceivableError("Só cobranças vencidas podem ser protestadas", 409)
    if charge.protested_at is not None:
        return charge  # idempotente
    charge.protested_at = datetime.now(UTC)
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="receivable.protest", target=charge.id
    )
    db.commit()
    db.refresh(charge)
    return charge


def mark_paid(db: Session, *, charge_id: str, tenant_id: str, actor: str, by_ai: bool) -> Charge:
    """Baixa (simula webhook do banco): cria a transação na carteira e marca paga. Atômico.

    FOR UPDATE serializa pagamentos concorrentes da MESMA cobrança (webhooks são at-least-once)
    — sem isso, duas baixas paralelas dobrariam a receita na carteira. No-op no SQLite.
    """
    charge = db.scalar(select(Charge).where(Charge.id == charge_id).with_for_update())
    if charge is None:
        raise ReceivableError("Cobrança não encontrada", 404)
    if charge.status == STATUS_PAID:
        return charge
    if charge.status == STATUS_CANCELED:
        raise ReceivableError("Cobrança cancelada não pode ser paga", 409)

    tx = wallet_service.build_transaction(
        db, tenant_id=tenant_id, actor=actor, by_ai=by_ai,
        kind=charge.kind, method=charge.method, gross_cents=charge.amount_cents,
        description=charge.description or "Recebimento", client_id=charge.client_id,
        external_ref=charge.id,
    )
    charge.status = STATUS_PAID
    charge.transaction_id = tx.id
    if charge.agenda_event_id:
        ev = db.get(AgendaEvent, charge.agenda_event_id)
        if ev is not None:
            ev.status = STATUS_DONE  # não fica "atrasado" na agenda
    audit.record(db, tenant_id=tenant_id, actor=actor, action="receivable.paid", target=charge.id)
    db.commit()
    db.refresh(charge)
    return charge


def webhook_confirm(*, session_factory, tenant_id: str, charge_id: str) -> str:
    """Reconhecimento AUTOMÁTICO de pagamento (gateway). Abre a sessão do tenant e dá baixa —
    o que credita a Carteira (split) e libera o valor para saque. Sem ação manual do dono."""
    with session_factory(tenant_id) as db:
        charge = mark_paid(
            db, charge_id=charge_id, tenant_id=tenant_id, actor="gateway:webhook", by_ai=False
        )
        return charge.status


def cancel_charge(db: Session, *, charge_id: str, tenant_id: str, actor: str) -> Charge:
    charge = get_charge(db, charge_id)
    if charge.status == STATUS_PAID:
        raise ReceivableError("Cobrança paga não pode ser cancelada", 409)
    charge.status = STATUS_CANCELED
    audit.record(db, tenant_id=tenant_id, actor=actor, action="receivable.cancel", target=charge.id)
    db.commit()
    db.refresh(charge)
    return charge


def _money(cents: int) -> str:
    return f"R$ {cents / 100:.2f}".replace(".", ",")


def _compose_dunning(name: str, amount_cents: int, due: date, description: str) -> str:
    """Mensagem de cobrança amigável. Usa a IA (Claude) se houver chave; senão, template.

    PII: enviamos o placeholder [NOME] ao Claude e reinserimos o nome real localmente.
    """
    valor = _money(amount_cents)
    venc = due.strftime("%d/%m/%Y")
    desc = description or "sua cobrança"
    if not settings.anthropic_api_key:
        return (
            f"Olá {name}, tudo bem? Notamos que {desc} no valor de {valor} venceu em {venc}. "
            "Consegue dar uma olhadinha quando puder? Qualquer dúvida, estou à disposição! 🙂"
        )
    system = (
        "Você é um assistente de cobrança amigável de um pequeno negócio brasileiro. "
        "Escreva UMA mensagem curta de WhatsApp (2-3 frases) cobrando um pagamento em atraso, "
        "em tom cordial e respeitoso, em português do Brasil. Nunca ameace. Use o placeholder "
        "[NOME] onde aparecer o nome do cliente. Responda só com a mensagem."
    )
    user = f"Valor: {valor}\nVencimento: {venc}\nDescrição: {desc}\nNome do cliente: [NOME]"
    try:
        result = ai.complete(system=system, user_message=user, max_tokens=300)
        return result.text.strip().replace("[NOME]", name)
    except Exception:
        return (
            f"Olá {name}, tudo bem? Notamos que {desc} no valor de {valor} venceu em {venc}. "
            "Consegue dar uma olhadinha quando puder? Qualquer dúvida, estou à disposição! 🙂"
        )


def collect_with_ai(db: Session, *, charge_id: str, tenant_id: str, actor: str) -> dict:
    """A IA escreve uma cobrança amigável e 'envia' no WhatsApp do cliente (rastro de IA)."""
    charge = get_charge(db, charge_id)
    if charge.status != STATUS_OPEN:
        raise ReceivableError("Só cobranças em aberto podem ser cobradas", 409)
    client = db.get(Client, charge.client_id) if charge.client_id else None
    name = client.name if client else "cliente"
    recipient = (client.phone if client and client.phone else None) or name
    message = _compose_dunning(name, charge.amount_cents, charge.due_date, charge.description)
    status = whatsapp.send_text(to=recipient, text=message)
    db.add(
        Notification(
            tenant_id=tenant_id, channel="whatsapp", recipient=recipient,
            client_id=charge.client_id, message=message, status=status,
        )
    )
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="receivable.collect.ai",
        target=charge.id, is_ai=True,
    )
    db.commit()
    return {"message": message, "status": status}


def send_message(db: Session, *, charge_id: str, tenant_id: str, actor: str, text: str) -> dict:
    """Mensagem MANUAL (sem IA) ao cliente da cobrança."""
    text = (text or "").strip()
    if not text:
        raise ReceivableError("Mensagem vazia", 400)
    charge = get_charge(db, charge_id)
    client = db.get(Client, charge.client_id) if charge.client_id else None
    recipient = (client.phone if client and client.phone else None) or (
        client.name if client else "cliente"
    )
    status = whatsapp.send_text(to=recipient, text=text)
    db.add(
        Notification(
            tenant_id=tenant_id, channel="whatsapp", recipient=recipient,
            client_id=charge.client_id, message=text, status=status,
        )
    )
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="receivable.message", target=charge.id
    )
    db.commit()
    return {"message": text, "status": status}


def charge_messages(db: Session, *, charge_id: str) -> list[Notification]:
    """Histórico de mensagens enviadas ao cliente desta cobrança (mais recentes primeiro)."""
    charge = get_charge(db, charge_id)
    if not charge.client_id:
        return []
    return list(
        db.scalars(
            select(Notification)
            .where(Notification.client_id == charge.client_id)
            .order_by(Notification.created_at.desc())
        ).all()
    )


def summary(db: Session) -> dict:
    today = datetime.now(UTC).date()
    open_charges = list(db.scalars(select(Charge).where(Charge.status == STATUS_OPEN)).all())
    open_cents = sum(c.amount_cents for c in open_charges if c.due_date >= today)
    overdue = [c for c in open_charges if c.due_date < today]
    paid = db.scalar(
        select(func.coalesce(func.sum(Charge.amount_cents), 0)).where(Charge.status == STATUS_PAID)
    ) or 0
    return {
        "open_cents": open_cents,
        "overdue_cents": sum(c.amount_cents for c in overdue),
        "paid_cents": paid,
        "open_count": len([c for c in open_charges if c.due_date >= today]),
        "overdue_count": len(overdue),
    }
