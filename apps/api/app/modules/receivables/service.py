"""Regras de Contas a Receber: criar cobrança, baixa (→ carteira), resumo de inadimplência.

Integra com a Carteira (baixa cria Transaction com split) e com a Agenda (vencimento vira evento).
Tudo numa única transação por operação.
"""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core import ai, audit, payment_gateway, whatsapp
from app.core.recurrence import advance, occurrences
from app.db.base import _uuid
from app.modules.agenda.models import (
    KIND_COBRANCA_RECEBER,
    PRIORITY_NORMAL,
    STATUS_DONE,
    STATUS_SCHEDULED,
    AgendaEvent,
)
from app.modules.chart_of_accounts import service as chart_service
from app.modules.contracts import service as contracts_service
from app.modules.cost_centers import service as cost_centers_service
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

logger = logging.getLogger("e1p.receivables")

# Eventos do Asaas que significam "pagamento reconhecido" (compensado/confirmado).
_ASAAS_PAID_EVENTS = {"PAYMENT_RECEIVED", "PAYMENT_CONFIRMED"}

# Story 5.6 (decisão de arquitetura — Aria/quality_gate): o rendimento de investimento vira uma
# `Charge` sintética JÁ baixada (status=paid), construída direto por `investments.register_yield` —
# nunca passa por mark_paid/split. Ela é um lançamento de RECEITA FINANCEIRA (entra na DRE), NÃO uma
# cobrança de cliente. Portanto NÃO deve poluir as superfícies de Contas a Receber (a lista de
# cobranças e o "Recebido"/`paid_cents` do resumo, que é uma superfície de RECONCILIAÇÃO de
# recebíveis de cliente). Filtramos a LEITURA por este prefixo de `external_ref`. A string duplica
# `investments.EXTERNAL_REF_PREFIX` DE PROPÓSITO: `investments` já depende de `receivables` (importa
# Charge/STATUS_PAID); importar de volta criaria dependência circular. Mantido em sincronia por
# comentário cruzado (ver `app/modules/investments/models.py`).
_INVESTMENT_REF_PREFIX = "investment:"


class ReceivableError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _payment_code(method: str, charge_id: str) -> str:
    """Stub do gateway (usado quando o gateway real não está configurado — graceful degradation)."""
    if method == "pix":
        return f"00020126-PIX-COPIA-E-COLA-{charge_id}"
    if method == "boleto":
        return f"34191.79001 01043.510047 91020.150008 1 0000{charge_id[:8]}"
    return f"https://pay.e1p.com/c/{charge_id}"  # link de cartão


def gateway_reference(tenant_id: str, charge_id: str) -> str:
    """external_reference enviado ao gateway: embute `tenant_id:charge_id` para correlacionar o
    webhook de volta SEM introduzir uma consulta global sem RLS (Regra de Ouro nº 1)."""
    return f"{tenant_id}:{charge_id}"


def is_overdue(charge: Charge, today: date | None = None) -> bool:
    today = today or datetime.now(UTC).date()
    return charge.status == STATUS_OPEN and charge.due_date < today


def _not_investment_yield():
    """Predicado SQL que exclui as `Charge` sintéticas de rendimento de investimento (Story 5.6).

    ⚠️ LÓGICA TERNÁRIA SQL: `Charge.external_ref` é nullable e cobranças NORMAIS têm NULL. Um
    `external_ref NOT LIKE 'investment:%'` PURO avaliaria `NOT (NULL LIKE ...)` = NULL (falsy) e
    excluiria TODAS as cobranças normais (bug silencioso). Por isso o `coalesce(external_ref, '')`:
    cobrança normal vira '' e passa no NOT LIKE; só a Charge de rendimento é filtrada."""
    return func.coalesce(Charge.external_ref, "").not_like(f"{_INVESTMENT_REF_PREFIX}%")


def _apply_gateway(
    db: Session, *, tenant_id: str, charge: Charge
) -> payment_gateway.GatewayChargeResult | None:
    """Se o gateway real estiver configurado, cria a cobrança registrada e devolve o resultado
    (linha digitável/Pix reais + status). Qualquer falha degrada para o stub (devolve None) — a
    criação da cobrança NUNCA quebra por causa do gateway."""
    if not payment_gateway.is_configured():
        return None
    client = db.get(Client, charge.client_id) if charge.client_id else None
    payer_name = client.name if client else (charge.description or "Cliente")
    payer_document = client.document if client else None
    try:
        result = payment_gateway.create_registered_charge(
            method=charge.method,
            amount_cents=charge.amount_cents,
            due_date=charge.due_date,
            payer_name=payer_name,
            payer_document=payer_document,
            external_reference=gateway_reference(tenant_id, charge.id),
        )
    except payment_gateway.GatewayError:
        logger.exception(
            "[receivables] gateway falhou para charge=%s — degradando para stub", charge.id
        )
        return None
    charge.gateway_provider = result.provider
    charge.gateway_charge_id = result.gateway_charge_id
    charge.gateway_status_raw = result.status
    if result.payment_code:
        charge.payment_code = result.payment_code
    return result


def build_charge(db: Session, *, tenant_id: str, actor: str, data: ChargeCreate) -> Charge:
    """Cria a cobrança + evento de agenda na sessão SEM commitar.

    Permite que outros módulos (ex.: Orçamentos ao aprovar) gerem a cobrança atomicamente
    junto com sua própria mutação, num único commit.
    """
    # Story 5.2: valida o vínculo opcional ao plano de contas (404 se apontar p/ conta
    # inexistente/de outro tenant — a RLS já esconde a linha cross-tenant). Ponto de criação ÚNICO,
    # então qualquer caller (inclusive o dominó de Orçamentos) herda a validação.
    if data.chart_account_id and not chart_service.exists(db, data.chart_account_id):
        raise ReceivableError("Conta do plano de contas não encontrada", 404)
    # Story 5.4: valida o vínculo opcional ao contrato (404 se apontar p/ contrato inexistente/de
    # outro tenant — a RLS já esconde a linha cross-tenant). Ponto de criação ÚNICO, então qualquer
    # caller (inclusive o dominó de Orçamentos) herda a validação.
    if data.contract_id and not contracts_service.exists(db, data.contract_id):
        raise ReceivableError("Contrato não encontrado", 404)
    # Story 5.5: valida o vínculo opcional ao centro de custo (2ª dimensão). 404 se apontar p/ um
    # centro inexistente/de outro tenant — a RLS já esconde a linha cross-tenant. Ponto de criação
    # ÚNICO, então qualquer caller (inclusive o dominó de Orçamentos) herda a validação.
    if data.cost_center_id and not cost_centers_service.exists(db, data.cost_center_id):
        raise ReceivableError("Centro de custo não encontrado", 404)
    charge = Charge(
        tenant_id=tenant_id,
        client_id=data.client_id,
        description=data.description,
        kind=data.kind,
        method=data.method,
        amount_cents=data.amount_cents,
        due_date=data.due_date,
        # competência (regime de competência/DRE): fallback = vencimento quando omitida.
        competence_date=data.competence_date or data.due_date,
        chart_account_id=data.chart_account_id,
        contract_id=data.contract_id,
        cost_center_id=data.cost_center_id,
        status=STATUS_OPEN,
    )
    db.add(charge)
    db.flush()  # popula charge.id (default aplicado no flush)
    # Default = stub; se o gateway real estiver configurado, _apply_gateway sobrescreve o código.
    charge.payment_code = _payment_code(data.method, charge.id)
    gateway_result = _apply_gateway(db, tenant_id=tenant_id, charge=charge)

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

    # Boleto: já gera o arquivo (PDF) e anexa à cobrança, com o vencimento e o código certos.
    if data.method == "boleto":
        _attach_boleto(db, tenant_id=tenant_id, charge=charge, gateway=gateway_result)

    audit.record(db, tenant_id=tenant_id, actor=actor, action="receivable.create", target=charge.id)
    return charge


def _attach_boleto(
    db: Session,
    *,
    tenant_id: str,
    charge: Charge,
    gateway: payment_gateway.GatewayChargeResult | None = None,
) -> None:
    from app.core.boleto import generate_boleto_pdf
    from app.modules.attachments.models import Attachment
    from app.modules.auth.models import Tenant

    tenant = db.get(Tenant, tenant_id)
    client = db.get(Client, charge.client_id) if charge.client_id else None
    # Com gateway real: usa a linha digitável REGISTRADA (já em charge.payment_code). O PDF é
    # regenerado com esse código real; o boleto bancário oficial fica em gateway.boleto_url
    # (bankSlipUrl) — embuti-lo como bytes exige validar o endpoint real do provedor (TODO).
    pdf = generate_boleto_pdf(
        payee=tenant.legal_name if tenant else "",
        payer=client.name if client else (charge.description or "Cliente"),
        amount_cents=charge.amount_cents,
        due_date=charge.due_date,
        code=charge.payment_code,
    )
    label = "boleto"
    db.add(Attachment(
        tenant_id=tenant_id, owner_type="charge", owner_id=charge.id, label=label,
        filename=f"boleto-{charge.id[:8]}.pdf", content_type="application/pdf",
        size=len(pdf), data=pdf,
    ))


def create_charge(db: Session, *, tenant_id: str, actor: str, data: ChargeCreate) -> Charge:
    """Cria a cobrança. Se recorrente, gera N cobranças (uma por vencimento), cada uma com seu
    código e seu evento na Agenda — assim cada repetição recebe seu próprio boleto/registro."""
    n = occurrences(data.recurrence, data.recurrence_count)
    group = _uuid() if n > 1 else None
    first: Charge | None = None
    for i in range(n):
        updates = {"due_date": advance(data.due_date, data.recurrence, i)}
        # Se a competência foi informada, avança em paralelo ao vencimento (cada ocorrência cai no
        # seu período). Se omitida, o build_charge usa o due_date da ocorrência.
        if data.competence_date is not None:
            updates["competence_date"] = advance(data.competence_date, data.recurrence, i)
        occ = data.model_copy(update=updates)
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
    # Story 5.6: exclui os lançamentos de rendimento de investimento (não são cobranças de cliente).
    stmt = select(Charge).where(_not_investment_yield()).order_by(Charge.due_date)
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
    # Story 5.2: reclassificação (competência/conta do plano de contas). Não toca no caminho de
    # dinheiro; competence_date NÃO segue o due_date aqui (edição explícita é a fonte da verdade).
    if data.competence_date is not None:
        charge.competence_date = data.competence_date
    if data.chart_account_id is not None:
        if data.chart_account_id == "":
            charge.chart_account_id = None
        elif not chart_service.exists(db, data.chart_account_id):
            raise ReceivableError("Conta do plano de contas não encontrada", 404)
        else:
            charge.chart_account_id = data.chart_account_id
    # Story 5.4: (re)vincular/desvincular do contrato. "" desvincula (bucket "Empresa"); um id
    # inexistente/de outro tenant → 404. Metadado analítico, não toca no caminho de dinheiro.
    if data.contract_id is not None:
        if data.contract_id == "":
            charge.contract_id = None
        elif not contracts_service.exists(db, data.contract_id):
            raise ReceivableError("Contrato não encontrado", 404)
        else:
            charge.contract_id = data.contract_id
    # Story 5.5: (re)vincular/desvincular do centro de custo (2ª dimensão). "" desvincula ("Não
    # atribuído"); id inexistente/de outro tenant → 404. Metadado analítico, não toca no dinheiro.
    if data.cost_center_id is not None:
        if data.cost_center_id == "":
            charge.cost_center_id = None
        elif not cost_centers_service.exists(db, data.cost_center_id):
            raise ReceivableError("Centro de custo não encontrado", 404)
        else:
            charge.cost_center_id = data.cost_center_id

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
    # Story 5.2: registra a data de pagamento (regime de caixa). Dentro do bloco FOR UPDATE e após
    # a guarda de idempotência (status já PAID → return acima), então paid_at é setado UMA vez —
    # um reenvio de webhook não sobrescreve a data da primeira baixa.
    charge.paid_at = datetime.now(UTC)
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
    o que credita a Carteira (split) e libera o valor para saque. Sem ação manual do dono.

    Contrato interno estável — preservado exatamente (chamado pela rota de webhook e por testes)."""
    with session_factory(tenant_id) as db:
        charge = mark_paid(
            db, charge_id=charge_id, tenant_id=tenant_id, actor="gateway:webhook", by_ai=False
        )
        return charge.status


def _validate_webhook_secret(*, is_provider_payload: bool, body: dict, token: str | None) -> None:
    """Fail-closed quando GATEWAY_WEBHOOK_SECRET está definido; aberto (dev) quando vazio.

    - Payload real do provedor (Asaas): valida o token vindo do HEADER.
    - Payload interno (dev/teste): valida o campo `secret` do corpo (retrocompatível)."""
    secret = settings.gateway_webhook_secret
    if not secret:
        return  # dev: webhook aberto para testes (o segredo vazio some em produção)
    expected = token if is_provider_payload else body.get("secret", "")
    if expected != secret:
        raise ReceivableError("Segredo do webhook inválido", 401)


def _resolve_webhook(body: dict, token: str | None) -> tuple[str, str] | None:
    """Extrai (tenant_id, charge_id) do payload do webhook, validando o segredo. Devolve None
    quando o evento deve ser ignorado (ex.: status != pago). Levanta ReceivableError (401/400)
    em segredo inválido ou payload malformado.

    Suporta DOIS formatos:
    - Real (Asaas): {"event": "PAYMENT_RECEIVED", "payment": {"externalReference": "tenant:charge"}}
    - Interno (dev/teste): {"tenant_id", "charge_id", "status", "secret"}
    """
    is_provider_payload = "event" in body or "payment" in body
    _validate_webhook_secret(is_provider_payload=is_provider_payload, body=body, token=token)

    if is_provider_payload:
        event = body.get("event")
        if event not in _ASAAS_PAID_EVENTS:
            return None  # evento não-financeiro/não-pago: ignorar
        payment = body.get("payment") or {}
        external = payment.get("externalReference") or ""
        tenant_id, sep, charge_id = external.partition(":")
        if not sep or not tenant_id or not charge_id:
            raise ReceivableError(
                "externalReference ausente/inválido no webhook do gateway", 400
            )
        return tenant_id, charge_id

    # Payload interno de dev/teste.
    if body.get("status", "paid") != "paid":
        return None
    tenant_id = body.get("tenant_id")
    charge_id = body.get("charge_id")
    if not tenant_id or not charge_id:
        raise ReceivableError("payload de webhook incompleto", 400)
    return tenant_id, charge_id


def process_webhook(*, session_factory, body: dict, token: str | None) -> dict:
    """Ponto de entrada do webhook: valida o segredo, resolve (tenant, charge) do payload real ou
    interno e reusa `webhook_confirm` (idempotente, com FOR UPDATE) para dar a baixa."""
    resolved = _resolve_webhook(body, token)
    if resolved is None:
        return {"status": "ignored"}
    tenant_id, charge_id = resolved
    status = webhook_confirm(
        session_factory=session_factory, tenant_id=tenant_id, charge_id=charge_id
    )
    return {"status": status}


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
    # open/overdue filtram por STATUS_OPEN — a Charge de rendimento nasce STATUS_PAID, então já não
    # entra aqui (não precisa do filtro de investimento). Só `paid` (abaixo) somaria o rendimento.
    open_charges = list(db.scalars(select(Charge).where(Charge.status == STATUS_OPEN)).all())
    open_cents = sum(c.amount_cents for c in open_charges if c.due_date >= today)
    overdue = [c for c in open_charges if c.due_date < today]
    # Story 5.6: "Recebido" é reconciliação de recebíveis de CLIENTE — exclui rendimento de
    # investimento (que é receita financeira, contabilizada na DRE, não recebimento de cobrança).
    paid = db.scalar(
        select(func.coalesce(func.sum(Charge.amount_cents), 0))
        .where(Charge.status == STATUS_PAID)
        .where(_not_investment_yield())
    ) or 0
    return {
        "open_cents": open_cents,
        "overdue_cents": sum(c.amount_cents for c in overdue),
        "paid_cents": paid,
        "open_count": len([c for c in open_charges if c.due_date >= today]),
        "overdue_count": len(overdue),
    }
