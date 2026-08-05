"""Regras de Contas a Receber: criar cobrança, baixa (→ carteira), resumo de inadimplência.

Integra com a Carteira (baixa cria Transaction com split) e com a Agenda (vencimento vira evento).
Tudo numa única transação por operação.
"""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core import ai, audit, payment_gateway
from app.core.recurrence import advance, occurrences

# O estado é DERIVADO da data, nunca escolhido (Story 8.15 AC5, herdando a 8.14). O helper é
# **público e neutro** (`app/core/`) exatamente para que os dois lados do dinheiro o compartilhem —
# **importar, nunca copiar** (`app/core/scheduling.py`, docstring).
from app.core.scheduling import janela_de_caixa, status_por_data
from app.db.base import _uuid

# ⚠️ **Duas palavras `scheduled` neste arquivo, e elas NÃO são a mesma coisa** — a mesma colisão que
# `payables/service.py` documenta desde a 8.14. O `scheduled` da Agenda quer dizer *"este evento
# ainda está pendente"*; o `scheduled` de `receivables` (Story 8.15) quer dizer *"o crédito já tem
# dia marcado"* — que, do ponto de vista da Agenda, deixa o evento **`done`**. Os dois vocabulários
# apontam para lados opostos no mesmo instante, então o da Agenda entra com prefixo: um `import` nu
# faria a colisão passar como sombreamento silencioso.
from app.modules.agenda.models import (
    KIND_COBRANCA_RECEBER,
    PRIORITY_NORMAL,
    AgendaEvent,
)
from app.modules.agenda.models import (
    STATUS_DONE as AGENDA_STATUS_DONE,
)
from app.modules.agenda.models import (
    STATUS_SCHEDULED as AGENDA_STATUS_PENDENTE,
)

# ⚠️ **A direção de import de NEGÓCIO → BANCO (Regra dos Planos §1.3d, Story 8.9 AC10).**
# `receivables` **pode** importar `app.modules.bank`; `app.modules.bank` **nunca** importa
# `receivables`. A volta é proibida e o gate `test_bank_nao_importa_payables` (AST **e** texto cru)
# a reprova.
from app.modules.bank import origin as bank_origin
from app.modules.bank import service as bank_service
from app.modules.bank.models import SOURCE_CHARGE, BankAccount
from app.modules.chart_of_accounts import service as chart_service
from app.modules.contracts import service as contracts_service
from app.modules.cost_centers import service as cost_centers_service
from app.modules.crm.models import Client
from app.modules.notifications import service as notifications_service
from app.modules.notifications.models import Notification
from app.modules.receivables.models import (
    STATUS_CANCELED,
    STATUS_OPEN,
    STATUS_PAID,
    STATUS_SCHEDULED,
    Charge,
)
from app.modules.receivables.schemas import ChargeCreate
from app.modules.wallet import service as wallet_service
from app.modules.whatsapp_templates.models import PURPOSE_CHARGE_REMINDER

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
        # `None` = o router serializa `str(e)` como sempre. Só o erro ACIONÁVEL abaixo preenche.
        self.detail: dict | None = None


# ── O 409 ACIONÁVEL, no MESMO formato que a Story 8.12 fixou (AC9) ────────────────────────────
#
# ⚠️ **A string é duplicada de `payables.service.ACAO_CADASTRAR_CONTA` DE PROPÓSITO**, e a sincronia
# é garantida por **teste**, não por comentário: `test_receivables_off_rail.py::
# test_a_acao_do_409_e_a_MESMA_string_de_payables` compara as duas constantes. Fazer `receivables`
# importar `payables` só por causa de uma palavra seria acoplamento gratuito entre dois módulos de
# negócio que, por design, não se conhecem — exatamente o motivo pelo qual
# `app/core/scheduling.py` nasceu neutro (correção do @po na 8.14). É o mesmo precedente de
# `_INVESTMENT_REF_PREFIX` neste arquivo, com a diferença de que aqui existe um teste no lugar do
# comentário cruzado.
ACAO_CADASTRAR_CONTA = "cadastrar_conta"

SEM_CONTA_MSG = (
    "Para registrar que você recebeu direto na conta, o e1p precisa saber em qual conta bancária "
    "o dinheiro caiu — é isso que faz o crédito aparecer no seu extrato e a conferência valer "
    "alguma coisa. Cadastre a sua conta bancária uma vez e o registro segue normalmente."
)

_CONTA_ARQUIVADA_MSG = (
    "A conta bancária escolhida está arquivada e não recebe lançamentos novos. Escolha outra "
    "conta ou cadastre a conta que você usa hoje — com o saldo de abertura do dia."
)


class ContaBancariaNecessaria(ReceivableError):
    """**409 ACIONÁVEL** — o formato do payload é CONTRATO, não detalhe de implementação.

        {"detail": {"acao": "cadastrar_conta", "mensagem": "..."}}

    Mesmo shape da Story 8.12 (`payables.service.ContaBancariaNecessaria`), consumido pela mesma
    tela de frontend (`features/pagar/baixa.ts::acaoCadastrarConta`, que reconhece por `acao` e
    **nunca** por substring da mensagem). Inventar um segundo formato aqui obrigaria a UI a
    aprender duas maneiras de reconhecer a mesma situação — que é como um contrato de erro deixa
    de ser contrato.

    ⚠️ **Nunca use este erro para uma conta que EXISTE em outro tenant.** Ali a resposta é **404**
    (`bank_service.get_account`, fail-closed pela RLS): 409 confirmaria a existência da linha.
    """

    def __init__(self, mensagem: str = ""):
        mensagem = mensagem or SEM_CONTA_MSG
        super().__init__(mensagem, 409)
        self.detail = {"acao": ACAO_CADASTRAR_CONTA, "mensagem": mensagem}


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


def is_overdue(charge: Charge, today: date) -> bool:
    """*"Esta cobrança está atrasada?"* — depende de QUE DIA É HOJE **para o dono**.

    `today` é **obrigatório**, espelhando `payables.is_overdue` (a simetria entre os dois lados do
    dinheiro é normativa). O fallback antigo era `datetime.now(UTC).date()`: em UTC−3, das 21h à
    meia-noite, marcava como atrasada uma cobrança que só vence amanhã — e era o dono ligando
    para o cliente cobrar uma dívida que não existia ainda.
    """
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
            # Volta a "pendente" na Agenda (deixa de ficar vermelho se atrasara).
            ev.status = AGENDA_STATUS_PENDENTE
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
            ev.status = AGENDA_STATUS_PENDENTE
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
    if not is_overdue(charge, _today(db)):
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
    # ── ⚠️ **[Story 8.15, DEFESA 4] O no-op do webhook atrasado deixa de ser ACIDENTE.** ────────
    #
    # Até aqui esta linha era só a guarda de reenvio de webhook (at-least-once). A partir do
    # `settle_off_rail`, ela **também** é o que impede um webhook do gateway, chegando DEPOIS de o
    # dono ter registrado que recebeu direto na conta, de criar uma `Transaction` + um
    # `PlatformEarning` sobre dinheiro que **nunca passou pela e1p** — GMV inflado no painel do
    # Master, sem estorno possível (a dívida `platform_earnings → transaction` segue aberta).
    #
    # ⚠️ **`scheduled` ENTROU AQUI, e sem ele a defesa tem um buraco de dias:** uma cobrança
    # liquidada fora do trilho com data futura fica `scheduled` até o worker promovê-la, e um
    # webhook nessa janela atravessaria um `if` que só olhasse `STATUS_PAID`.
    #
    # ⚠️ **Se você for refinar esta idempotência** (ex.: *"reenvio só é no-op se o
    # `gateway_charge_id` for o mesmo"*), leia `test_receivables_off_rail.py::
    # test_webhook_apos_recebimento_fora_do_trilho_e_noop` **antes**: o silêncio aqui é escolhido,
    # não herdado.
    if charge.status in (STATUS_PAID, STATUS_SCHEDULED):
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
            ev.status = AGENDA_STATUS_DONE  # não fica "atrasado" na agenda
    audit.record(db, tenant_id=tenant_id, actor=actor, action="receivable.paid", target=charge.id)
    db.commit()
    db.refresh(charge)
    return charge


# ══════════════════════════════════════════════════════════════════════════════════════════════
# A PORTA FORA DO TRILHO (Story 8.15) — e a INVARIANTE DO TRILHO que ela mantém de pé
# ══════════════════════════════════════════════════════════════════════════════════════════════
#
# > **Para toda `Charge` liquidada, exatamente UM de `transaction_id` e `bank_account_id` é
# > não-nulo. Nunca os dois, nunca nenhum.**
# >
# > - `transaction_id IS NOT NULL` → **trilho** (plano 1): split 40/30/20 aplicado,
# >   `PlatformEarning` criado, **zero** movimento bancário. O dinheiro está na Carteira da e1p e
# >   só encosta na conta do dono no payout (Onda 3);
# > - `bank_account_id IS NOT NULL` → **fora do trilho** (plano 3): **zero** `Transaction`,
# >   **zero** `PlatformEarning`, um `bank_transaction` de crédito. O dinheiro nunca passou
# >   pela e1p.
#
# **NÃO existe coluna `payment_route`**: a rota é DERIVADA dos dois ponteiros
# (`"trilho" if charge.transaction_id else "banco"`). Um rótulo separado pode divergir do fato e
# vira a terceira fonte de verdade — a lição D-3, aplicada preventivamente. O gate
# `test_money_planes.py::test_origin_type_e_payment_route_nao_existem` reprova quem a criar.
#
# A varredura da invariante mora em `tests/test_invariante_do_trilho.py`; as outras quatro defesas,
# em `tests/test_receivables_off_rail.py`. **Nenhuma delas é "tomar cuidado".**


def _today(db: Session, *, now: datetime | None = None) -> date:
    """Hoje NO FUSO DO TENANT — a MESMA âncora de `is_overdue`, `summary` e `payables._today`."""
    from app.modules.settings.service import hoje_do_tenant

    return hoje_do_tenant(db, now=now)


def _traduz_bank_error(call):
    """Executa uma chamada ao módulo `bank` traduzindo `BankError` → `ReceivableError`.

    A fronteira de módulo existe também para os ERROS: sem esta tradução, um `BankError` subindo
    de `sync_origin_movement` atravessaria o `except ReceivableError` do router e viraria **500** —
    um 422 legítimo (data, valor) apareceria ao usuário como falha do servidor. Mesma disciplina de
    `payables.service._traduz_bank_error`; o `status_code` é preservado.
    """
    try:
        return call()
    except bank_service.BankError as e:
        raise ReceivableError(str(e), e.status_code) from e


def _conta_do_recebimento(db: Session, bank_account_id: str) -> BankAccount:
    """Resolve a conta do recebimento: **409 acionável, 404, 409 — nesta ordem, e por este motivo.**

    Mesma escada de `payables.service._conta_de_baixa` (AC9 manda reusar a decisão F7 inteira,
    não só o formato do corpo):

    1. **Tenant sem NENHUMA conta ativa → 409 acionável**, *antes* de olhar o id recebido. É esta
       ordem que torna o erro alcançável a partir da rota: como `bank_account_id` é obrigatório, um
       tenant sem contas só consegue mandar um id qualquer — e um 404 ali diria "esse id não
       existe" quando o fato é "você ainda não cadastrou conta nenhuma". Também **não vaza
       existência**: com zero contas próprias, *todo* id recebe a mesma resposta, inclusive o id
       real de outro tenant;
    2. **Id desconhecido (ou de outro tenant, escondido pela RLS) → 404 fail-closed**;
    3. **Conta arquivada → 409 acionável**: a conta existe, mas encerrada não recebe lançamento
       novo, e a saída é a mesma do caso (1).
    """
    if not bank_service.list_accounts(db):
        raise ContaBancariaNecessaria()
    acc = _traduz_bank_error(lambda: bank_service.get_account(db, bank_account_id))
    if acc.archived_at is not None:
        raise ContaBancariaNecessaria(_CONTA_ARQUIVADA_MSG)
    return acc


def _valida_data_do_recebimento(received_on: date, acc: BankAccount) -> date:
    """A guarda da data do crédito: **só o PISO**. 422 — nunca trunca em silêncio.

    A comparação NÃO é reescrita aqui: quem a aplica é `bank.service.validate_posted_at_floor`,
    pública desde a 8.9 exatamente para isto. O que esta função acrescenta é a **mensagem que
    nomeia as duas saídas** (mover a abertura da conta ou escolher outra) — a genérica do módulo
    `bank` explica a fórmula do saldo, e quem está registrando um Pix antigo precisa saber o que
    fazer, não por que a soma dobraria.

    **Sem teto**, e a ausência é a regra do AC5: `received_on` futuro é um recebimento **agendado**
    (`scheduled`), não um erro. O corte é por `source` — `SOURCES_EXTERNA` continua recusando data
    futura em `bank.service._validate_posted_at`.
    """
    try:
        bank_service.validate_posted_at_floor(received_on, acc)
    except bank_service.BankError as e:
        raise ReceivableError(
            f"Esta conta bancária só existe no e1p a partir de "
            f"{acc.opening_date.isoformat()}, então um recebimento em "
            f"{received_on.isoformat()} não entraria no extrato dela. Mova a abertura desta conta "
            f"para antes de {received_on.strftime('%d/%m')} e informe o saldo daquele dia, ou "
            "escolha outra conta.",
            422,
        ) from e
    return received_on


def _descricao_do_movimento(charge: Charge, client: Client | None) -> str:
    """A descrição que vai para `bank_transactions.raw_description`.

    Quem lê o extrato está procurando *de quem* veio o dinheiro e *por quê* — os dois quando
    houver os dois. Espelho de `payables._descricao_do_movimento`, com a ordem invertida porque
    numa entrada o pagador é o que identifica a linha.
    """
    partes = [texto for texto in (client.name if client else "", charge.description) if texto]
    return " — ".join(partes) or "Recebimento"


def _data_de_caixa(charge: Charge) -> date | None:
    """`charge.paid_at` como data de calendário em UTC (ou `None`).

    Coluna `DateTime(timezone=True)`: o Postgres devolve tz-aware, o SQLite dos testes devolve
    naive (já em UTC). Normalizar aqui é o mesmo cuidado de `payables._as_utc_date`, na versão
    que basta para um atributo do ORM (aquela existe para o TEXTO que o SQLite devolve em
    agregações `MIN/MAX`, que não acontece neste caminho).
    """
    if charge.paid_at is None:
        return None
    dt = charge.paid_at
    return (dt if dt.tzinfo is None else dt.astimezone(UTC)).date()


def _sincroniza_movimento(
    db: Session,
    charge: Charge,
    *,
    tenant_id: str,
    actor: str,
    client: Client | None,
    bank_account_id: str | None,
    posted_at: date | None,
) -> None:
    """O **único** ponto deste módulo que escreve o razão bancário. Não commita.

    ⚠️ **Nenhum segundo caminho de escrita.** Se aparecer um `BankTransaction(...)` com
    `source='charge'` fora de `bank.origin.sync_origin_movement`, a Regra da Origem fica
    inauditável — o gate `test_chamadores_do_sincronizador_estao_na_allowlist` existe para que a
    segunda porta não passe despercebida (e este módulo entrou na allowlist com esta story).

    O cache (`charge.bank_transaction_id`) é gravado com **o que o sincronizador devolveu**,
    sempre — é assim que ele nunca diverge do `origin_id`.
    """
    movimento = _traduz_bank_error(
        lambda: bank_origin.sync_origin_movement(
            db,
            tenant_id=tenant_id,
            actor=actor,
            source=SOURCE_CHARGE,
            origin_id=charge.id,
            bank_account_id=bank_account_id,
            posted_at=posted_at,
            # **POSITIVO — é entrada.** O sinal é interno à tabela de movimentos (invariante (b)
            # de `BankTransaction`) e `+abs()` é deliberado: `charge.amount_cents` já é `> 0` por
            # schema, mas um dado legado negativo viraria uma SAÍDA no extrato.
            amount_cents=abs(charge.amount_cents) if bank_account_id else None,
            description=_descricao_do_movimento(charge, client),
            # PII de terceiro: o cliente nunca contratou com a e1p. A Onda 2 não chama IA em lugar
            # nenhum (epic §4.4), então o anonimizador não entra aqui — ele volta a ser obrigatório
            # nas Ondas 4 e 5.
            counterparty_name=client.name if client else "",
            counterparty_document=(client.document if client and client.document else ""),
            operation_nature=None,
        )
    )
    charge.bank_account_id = bank_account_id
    charge.bank_transaction_id = movimento.id if movimento is not None else None


def settle_off_rail(
    db: Session,
    *,
    charge_id: str,
    tenant_id: str,
    actor: str,
    bank_account_id: str,
    received_on: date | None = None,
) -> Charge:
    """Registra que a cobrança foi recebida DIRETO na conta do dono, **fora do trilho**. Commita.

    > **NUNCA chama `wallet`. NUNCA cria `Transaction` nem `PlatformEarning`.** Gera um
    > `bank_transaction` de **crédito** via `sync_origin_movement(source='charge')`, na MESMA
    > transação. `transaction_id` permanece **NULL para sempre** — é a metade "banco" da
    > INVARIANTE DO TRILHO.

    **Por que esta porta existe:** hoje não há caminho nenhum. O botão "Marcar paga" foi removido
    de propósito (só o webhook do gateway marca pago), então a cobrança paga por fora fica **em
    aberto para sempre** — o dinheiro não aparece em lugar nenhum e a régua segue mandando lembrete
    a quem já pagou.

    **O que muda, item a item** (AC2):
      - `status` = `paid` **ou** `scheduled`, **derivado de `received_on`** (AC5);
      - `paid_at` = `received_on` à meia-noite UTC (**regime de caixa**);
      - `competence_date` **intocada** (**regime de competência** — `receivables/models.py:6-9`,
        regra dura: mudar a data do recebimento move caixa, Projeção e o movimento bancário;
        **não** move DRE nem Lucratividade);
      - `bank_account_id` preenchido, `transaction_id` **NULL**;
      - o evento da Agenda vai para `done` — a cobrança sai da régua **porque deixou de ser
        `open`**, não porque alguém a excluiu;
      - um `bank_transaction` de `+amount_cents`, `source='charge'`, `origin_id=charge.id`,
        `status='matched'`, contraparte herdada do `Client`.

    **A ordem das guardas é a defesa 5** (AC8): `transaction_id IS NOT NULL` é checado **antes** da
    idempotência de status. Invertido, uma cobrança já paga pelo trilho cairia no `return` de
    idempotência e a tentativa de "corrigi-la" para fora do trilho passaria em silêncio — que é
    exatamente transformar dinheiro de plataforma em dinheiro de banco, o cruzamento de planos que
    originou o épico.

    **`scheduled` NÃO é idempotente aqui, e isso é o ponto** (mesma decisão de
    `payables.apply_paid`): uma cobrança agendada que recebe um registro novo (com o dia em que o
    dinheiro caiu de verdade) **atravessa** a guarda e re-deriva o estado. O movimento não duplica
    porque `sync_origin_movement` é upsert sobre `(source, origin_id)`: ele **move**, nunca cria
    um segundo. Já liquidada (`paid`) volta **inalterada**, sem re-datar — para corrigir conta ou
    data existe `update_off_rail_payment`.

    Args:
        bank_account_id: **OBRIGATÓRIO, sem default e sem `| None`** (AC9, fundador F7). Não há
            fallback para a conta primária aqui: o pré-preenchimento é da UI, e *"o que o
            pré-preenchimento evita é **construir**, não **confirmar**"*.
        received_on: `None` ⇒ **hoje**. Diferente do `payables.apply_paid` (que cai no `due_date`,
            fundador F10) **de propósito**: lá o gesto é *"paguei — provavelmente no vencimento"*;
            aqui o gesto é *"caiu na minha conta"*, um fato que o dono está observando agora. A
            assimetria é a mesma que separa `mark_paid` (fato atestado por terceiro) desta função.
    """
    charge = db.scalar(select(Charge).where(Charge.id == charge_id).with_for_update())
    if charge is None:
        raise ReceivableError("Cobrança não encontrada", 404)
    if charge.status == STATUS_CANCELED:
        raise ReceivableError("Cobrança cancelada não pode ser recebida", 409)
    # DEFESA 5 — a direção inversa, e ela vem ANTES da idempotência (ver a docstring).
    if charge.transaction_id is not None:
        raise ReceivableError(
            "Esta cobrança já foi paga pelo trilho do e1p: o dinheiro entrou na Carteira, com o "
            "split aplicado, e não caiu direto na sua conta bancária. Registrá-la como recebida "
            "fora do trilho faria o mesmo dinheiro existir nos dois planos.",
            409,
        )
    if charge.status == STATUS_PAID:
        return charge  # idempotente: já liquidada fora do trilho, não re-data

    # Ordem deliberada: TODA validação antes de qualquer escrita (mesma disciplina de
    # `bank.origin.sync_origin_movement`).
    acc = _conta_do_recebimento(db, bank_account_id)
    received_on = _valida_data_do_recebimento(
        received_on if received_on is not None else _today(db), acc
    )

    charge.status = status_por_data(
        received_on, _today(db), status_agendado=STATUS_SCHEDULED, status_pago=STATUS_PAID
    )
    # Meia-noite UTC da data de caixa — mesma convenção de `payables.apply_paid` e o mesmo cuidado
    # de data-de-calendário que o bug de fuso da Agenda (`CLAUDE.md` §6.0) ensinou.
    charge.paid_at = datetime.combine(received_on, time.min, tzinfo=UTC)
    if charge.agenda_event_id:
        ev = db.get(AgendaEvent, charge.agenda_event_id)
        if ev is not None:
            # `done` também no caminho `scheduled`: do ponto de vista da Agenda a cobrança deixou
            # de ser uma pendência: ela tem dia marcado. É o que permite `promote_scheduled`
            # promover sem tocar na Agenda.
            ev.status = AGENDA_STATUS_DONE
    client = db.get(Client, charge.client_id) if charge.client_id else None
    _sincroniza_movimento(
        db,
        charge,
        tenant_id=tenant_id,
        actor=actor,
        client=client,
        bank_account_id=acc.id,
        posted_at=received_on,
    )
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="receivable.settle_off_rail", target=charge.id
    )
    db.commit()
    db.refresh(charge)
    return charge


def update_off_rail_payment(
    db: Session,
    *,
    charge_id: str,
    tenant_id: str,
    actor: str,
    bank_account_id: str | None = None,
    received_on: date | None = None,
) -> Charge:
    """Corrige o **recebimento fora do trilho**: a conta bancária e/ou a data. Commita.

    Simétrica de `payables.update_payment`, e existe pelo mesmo motivo (F-D10): corrigir é evento
    **normal**, não excepcional. Sem ela, a alternativa seria desfazer + refazer — delete + recreate
    do movimento bancário e o evento da Agenda indo e voltando.

    - **restrita a cobranças fora do trilho** (`transaction_id IS NULL AND bank_account_id IS NOT
      NULL`). Cobrança do trilho → **409** (não há conta bancária a corrigir: o dinheiro está na
      Carteira); cobrança em aberto → **409** (não há recebimento a corrigir);
    - aceita `paid` **e** `scheduled`, e mudar `received_on` **move o estado** entre os dois —
      pela **mesma** derivação de `settle_off_rail` (`status_por_data`), nunca uma segunda cópia;
    - trocar a conta → **UPDATE na MESMA linha** do movimento (move, nunca duplica). Trocar a data
      → UPDATE de `posted_at`, revalidado contra a `opening_date` da conta de **destino**, que pode
      ter mudado no mesmo PATCH;
    - `competence_date` **não** é tocado (caixa × competência não se invertem).

    ⚠️ **`ChargeUpdate` NÃO é tocado, e a guarda é dupla** — a mesma disciplina que
    `bank.update_transaction` e `payables.update_payment` documentam "de propósito": o campo não
    existe no schema genérico **e** nenhuma função faz `setattr` genérico. Mantendo o PATCH
    genérico intacto, ninguém torna um campo editável em cobrança paga por acidente.

    **Não desfaz nada.** Desfazer um recebimento fora do trilho está FORA de escopo (F-D4) e não é
    o mesmo que corrigir conta ou data — que é o erro provável.
    """
    charge = db.scalar(select(Charge).where(Charge.id == charge_id).with_for_update())
    if charge is None:
        raise ReceivableError("Cobrança não encontrada", 404)
    if charge.transaction_id is not None:
        raise ReceivableError(
            "Esta cobrança entrou pelo trilho do e1p (o dinheiro caiu na Carteira, com o split "
            "aplicado). Não há conta bancária nem data de crédito a corrigir aqui.",
            409,
        )
    if charge.bank_account_id is None:
        raise ReceivableError(
            "Só uma cobrança registrada como recebida fora do trilho tem recebimento a corrigir. "
            "Para mexer em valor, vencimento ou descrição de uma cobrança em aberto, use a edição "
            "da cobrança.",
            409,
        )

    destino_id = bank_account_id if bank_account_id is not None else charge.bank_account_id
    acc = _conta_do_recebimento(db, destino_id)

    if received_on is None:
        # Data ausente = "não altera". `paid_at` é a data de caixa autoritativa.
        received_on = _data_de_caixa(charge) or charge.due_date
    received_on = _valida_data_do_recebimento(received_on, acc)

    charge.paid_at = datetime.combine(received_on, time.min, tzinfo=UTC)
    charge.status = status_por_data(
        received_on, _today(db), status_agendado=STATUS_SCHEDULED, status_pago=STATUS_PAID
    )
    client = db.get(Client, charge.client_id) if charge.client_id else None
    _sincroniza_movimento(
        db,
        charge,
        tenant_id=tenant_id,
        actor=actor,
        client=client,
        bank_account_id=acc.id,
        posted_at=received_on,
    )
    audit.record(
        db,
        tenant_id=tenant_id,
        actor=actor,
        action="receivable.payment_update",
        target=charge.id,
    )
    db.commit()
    db.refresh(charge)
    return charge


def contar_entradas_sem_conta_informada(
    db: Session, *, start: date, end: date
) -> tuple[int, int]:
    """**P2 da pré-condição do gate** (Story 8.16 AC8): recebimento fora do trilho sem conta.

    > `Charge`, `status ∈ {paid, scheduled}`, `paid_at::date` na janela, `transaction_id IS NULL`,
    > `bank_account_id IS NULL`, **e `_not_investment_yield()`**

    Devolve `(quantidade, soma_dos_valores_em_centavos)`. **Somente leitura.**

    ⚠️ **O `_not_investment_yield()` deste predicado é o BLOQUEIO 3 da onda (achado A-1), e sem ele
    o gate NUNCA abriria para nenhum tenant que registre rendimento.** A `Charge` sintética de
    rendimento de aplicação nasce `status='paid'`, `paid_at=now()`, `transaction_id=NULL` e
    `bank_account_id=NULL` (`investments.register_yield`): ela cai **inteira** nesta população se
    não for excluída — e a perna bancária dela é escopo da Onda 2b, declaradamente fora desta onda.
    Ela é **P3**, com contador e nota próprios (`contar_rendimentos_sem_perna_bancaria`).

    O predicado é **reusado, nunca reescrito**: ele já mora neste arquivo e inclui a guarda de
    lógica ternária SQL (`coalesce(external_ref, '')`) que um reescritor distraído perderia,
    excluindo **todas** as cobranças normais em silêncio. *"Duas cópias divergem — e já divergiram
    uma vez, entre dois @sm que não conversam"*: a Story 8.15 lembrou este predicado, a 8.16 o
    esqueceu, e é por isso que ele tem um lugar só.

    **Fora da população, por construção e não por omissão:** `Charge` do **trilho**
    (`transaction_id IS NOT NULL`). O dinheiro dela está na **Carteira**, não numa conta do dono, e
    ela **não deve** gerar movimento bancário até o payout (Regra dos Planos). Incluí-la é
    exatamente a leitura que tornava a pré-condição do gate **insatisfazível**.

    **Membro:** um Pix de R$ 1.400 registrado em 12/07 antes de a conta bancária existir → conta.
    **Não-membro:** uma cobrança paga pelo webhook do gateway em 12/07 → tem `transaction_id`.
    **Não-membro 2:** a `Charge` de rendimento de 12/07 → excluída aqui, contada em P3.
    """
    de, ate = janela_de_caixa(start, end)
    row = db.execute(
        select(func.count(), func.coalesce(func.sum(Charge.amount_cents), 0)).where(
            Charge.status.in_((STATUS_PAID, STATUS_SCHEDULED)),
            Charge.transaction_id.is_(None),
            Charge.bank_account_id.is_(None),
            _not_investment_yield(),
            Charge.paid_at.is_not(None),
            Charge.paid_at >= de,
            Charge.paid_at < ate,
        )
    ).one()
    return int(row[0] or 0), int(row[1] or 0)


def contar_rendimentos_sem_perna_bancaria(
    db: Session, *, start: date, end: date
) -> tuple[int, int]:
    """**P3 da pré-condição do gate** (Story 8.16 AC8): rendimento de aplicação sem perna bancária.

    > `Charge` com `external_ref LIKE 'investment:%'`, `paid_at::date` na janela

    Devolve `(quantidade, soma_dos_valores_em_centavos)`. **Somente leitura.**

    **Contador PRÓPRIO, e a separação é normativa** (ratificação §C-1.5): este termo **não fecha na
    Onda 2**. Ele fecha na **Onda 2b**, quando `register_yield` passar a gerar o movimento bancário
    correspondente. Somá-lo a P1/P2 prometeria na tela um prazo falso — *"isso some quando você
    terminar de corrigir os lançamentos"* sobre um termo que o dono **não tem como** corrigir.

    O predicado é a **negação** do mesmo `_not_investment_yield()` usado em P2 — literalmente o
    complemento, e não uma segunda escrita do `LIKE 'investment:%'`. As duas populações particionam
    as cobranças pelo mesmo corte, então elas não podem divergir.
    """
    de, ate = janela_de_caixa(start, end)
    row = db.execute(
        select(func.count(), func.coalesce(func.sum(Charge.amount_cents), 0)).where(
            ~_not_investment_yield(),
            Charge.paid_at.is_not(None),
            Charge.paid_at >= de,
            Charge.paid_at < ate,
        )
    ).one()
    return int(row[0] or 0), int(row[1] or 0)


def promote_scheduled(
    db: Session, *, tenant_id: str, actor: str, today: date | None = None
) -> int:
    """`scheduled → paid` para toda cobrança cujo dia do crédito chegou. Devolve quantas promoveu.

    **O irmão de `payables.service.promote_scheduled`, com a MESMA assinatura** (correção do @po na
    8.15 AC5): a **etapa 4** de `app.worker.run_sweep` chama as **duas** na mesma varredura — é a
    mesma pergunta (*"já chegou o dia?"*) sobre os dois lados do dinheiro, e uma quinta etapa seria
    a mesma regra em dois lugares.

    ⚠️ **O SALDO DERIVADO NÃO DEPENDE DESTE WORKER** (F-D11). O movimento bancário nasceu com
    `posted_at` = a data do crédito, e o saldo é **função da data** (`_movements_sums` filtra
    `posted_at <= until`): ele entra sozinho quando o dia chega, com o worker desligado, parado ou
    nem instalado. O que esta função move é **só o `status`** — para a lista de cobranças e o
    `scheduled_cents` do resumo pararem de mostrar como "agendada" uma cobrança que já caiu. A
    mesma disciplina vale para a Projeção (o recorte `paid_at::date > hoje` do AC6 faz a aritmética
    depender da **data**, não do status materializado).

    **Não toca em mais nada**, e cada omissão é deliberada:
    - `paid_at` **não** é re-datado (é a data de caixa que o dono informou; sobrescrevê-la por
      "hoje" inventaria um fato de caixa — Artigo IV);
    - `bank_account_id` / `bank_transaction_id` intactos (o movimento já está certo);
    - `transaction_id` **jamais** — promover não é entrar no trilho, e a Invariante do Trilho tem
      de sobreviver à promoção (há teste varrendo depois do worker);
    - o evento da Agenda já está `done` desde o registro;
    - `competence_date` **jamais** (caixa × competência não se invertem).

    **Idempotente:** rodar duas vezes seguidas promove zero na segunda. `today` é **injetável** —
    um contador preso ao relógio da máquina não é testável. Isolamento por RLS, sem filtro manual
    de `tenant_id` (Regra de Ouro nº 1).
    """
    today = today or _today(db)
    # Limite de TIMESTAMP em vez de `::date` (dialeto-agnóstico — o SQLite dos testes não tem
    # `::date`), mesmo padrão de `payables.promote_scheduled`. "A data já chegou" é
    # `paid_at::date <= today`, ou seja, `paid_at < meia-noite UTC de today+1`.
    limite = datetime.combine(today + timedelta(days=1), time.min, tzinfo=UTC)
    vencidas = list(
        db.scalars(
            select(Charge).where(
                Charge.status == STATUS_SCHEDULED,
                # Agendada sem data de caixa é estado inalcançável (a derivação exige a data); a
                # guarda existe porque `paid_at IS NULL` compararia como desconhecido em SQL e a
                # linha ficaria presa em `scheduled` para sempre, sem ninguém notar.
                Charge.paid_at.is_not(None),
                Charge.paid_at < limite,
            )
        ).all()
    )
    for charge in vencidas:
        charge.status = STATUS_PAID
        audit.record(
            db,
            tenant_id=tenant_id,
            actor=actor,
            action="receivable.scheduled_promoted",
            target=charge.id,
        )
    if vencidas:
        db.commit()
    return len(vencidas)


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
    """⚠️ **[Story 8.15] `scheduled` ENTROU na guarda, e a omissão seria um movimento órfão.**

    Antes desta story nenhuma `Charge` tinha perna bancária, então cancelar era só uma troca de
    status. A partir do `settle_off_rail`, uma cobrança `scheduled` **tem um `bank_transaction` de
    crédito futuro**: cancelá-la sem tocar no movimento deixaria o razão bancário afirmando *"este
    dinheiro vai entrar nesta conta"* sobre uma cobrança que não existe mais — a violação (c) da
    Regra da Origem (*"nunca deixa órfão"*), e ela apareceria como um crédito inexplicável em
    "Agendado para entrar".

    **Recusar é a resposta certa, e não é falta de funcionalidade:** desfazer um recebimento fora do
    trilho está explicitamente FORA de escopo (F-D4, epic §9.2), e a rota de correção do AC10 cobre
    o erro provável (conta ou data erradas). Cancelar uma cobrança que o dono declarou ter recebido
    é dizer duas coisas contraditórias sobre o mesmo dinheiro.
    """
    charge = get_charge(db, charge_id)
    if charge.status == STATUS_PAID:
        raise ReceivableError("Cobrança paga não pode ser cancelada", 409)
    if charge.status == STATUS_SCHEDULED:
        raise ReceivableError(
            "Esta cobrança já tem um recebimento registrado, com dia marcado para cair na sua "
            "conta. Se a conta ou a data estiverem erradas, corrija o recebimento; cancelar a "
            "cobrança deixaria um crédito anunciado no seu extrato sem nada por trás.",
            409,
        )
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


def _compose_dunning_phrase(name: str, amount_cents: int, due: date, description: str) -> str:
    """Só a FRASE de cobrança (variável 2 do template `charge_reminder`) — não a mensagem inteira.

    Usa a IA (Claude) se houver chave; senão, frase padrão. Mesma técnica de anonimização de PII
    de `_compose_dunning` (placeholder [NOME], reinserido localmente): o nome/valor/vencimento já
    são OUTRAS variáveis do template, então aqui só pedimos o motivo/tom da cobrança, sem repetir.
    """
    valor = _money(amount_cents)
    venc = due.strftime("%d/%m/%Y")
    desc = description or "sua cobrança"
    if not settings.anthropic_api_key:
        return "Notamos que sua cobrança está em aberto."
    system = (
        "Você é um assistente de cobrança amigável de um pequeno negócio brasileiro. "
        "Escreva APENAS UMA frase curta (sem saudação, sem repetir valor/data/nome — isso já "
        "aparece em outras partes da mensagem) explicando o motivo da cobrança em tom cordial e "
        "respeitoso, em português do Brasil. Nunca ameace. Use o placeholder [NOME] se precisar "
        "se referir ao cliente. Responda só com a frase."
    )
    user = f"Valor: {valor}\nVencimento: {venc}\nDescrição: {desc}\nNome do cliente: [NOME]"
    try:
        result = ai.complete(system=system, user_message=user, max_tokens=100)
        return result.text.strip().replace("[NOME]", name)
    except Exception:
        return "Notamos que sua cobrança está em aberto."


def _render_template_preview(body_text: str, variables: list[str]) -> str:
    """Substitui {{1}}, {{2}}, ... no corpo do template pelos valores já resolvidos.

    Duplica `funnels.service._render_template_preview` (função privada de módulo, ~4 linhas) —
    evitamos importar através de módulos por uma função tão pequena (preferência do projeto contra
    abstração prematura).
    """
    rendered = body_text
    for i, value in enumerate(variables, start=1):
        rendered = rendered.replace(f"{{{{{i}}}}}", value)
    return rendered


def collect_with_ai(db: Session, *, charge_id: str, tenant_id: str, actor: str) -> dict:
    """A IA escreve uma cobrança amigável e 'envia' no WhatsApp do cliente (rastro de IA).

    Se o tenant já vinculou um template APROVADO ao propósito `charge_reminder` (Configurações),
    envia via template (exigência da Meta para mensagens business-initiated): a IA só escreve a
    frase-motivo (variável 2), o resto (nome/valor/vencimento) é preenchido pelo sistema. Sem
    vínculo (ou template ainda não aprovado), cai no caminho antigo de texto livre — agora usando
    as credenciais do TENANT em vez do env global morto.
    """
    from app.modules.settings import service as settings_service
    from app.modules.whatsapp_templates.models import STATUS_APPROVED, WhatsappTemplate

    charge = get_charge(db, charge_id)
    if charge.status != STATUS_OPEN:
        raise ReceivableError("Só cobranças em aberto podem ser cobradas", 409)
    client = db.get(Client, charge.client_id) if charge.client_id else None
    name = client.name if client else "cliente"
    recipient = (client.phone if client and client.phone else None) or name

    profile = settings_service.get_profile(db, tenant_id)
    template_id = (profile.whatsapp_template_bindings or {}).get(PURPOSE_CHARGE_REMINDER)
    template = db.get(WhatsappTemplate, template_id) if template_id else None

    if template is not None and template.status == STATUS_APPROVED:
        valor = _money(charge.amount_cents)
        venc = charge.due_date.strftime("%d/%m/%Y")
        phrase = _compose_dunning_phrase(
            name, charge.amount_cents, charge.due_date, charge.description
        )
        variables = [name, phrase, valor, venc]
        message = _render_template_preview(template.body_text, variables)
        notifications_service.enqueue(
            db, tenant_id=tenant_id, channel="whatsapp", recipient=recipient,
            client_id=charge.client_id, message=message, purpose=PURPOSE_CHARGE_REMINDER,
            whatsapp_template_name=template.name, whatsapp_template_language=template.language,
            whatsapp_template_variables=variables,
        )
    else:
        message = _compose_dunning(name, charge.amount_cents, charge.due_date, charge.description)
        notifications_service.enqueue(
            db, tenant_id=tenant_id, channel="whatsapp", recipient=recipient,
            client_id=charge.client_id, message=message, purpose=PURPOSE_CHARGE_REMINDER,
        )

    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="receivable.collect.ai",
        target=charge.id, is_ai=True,
    )
    db.commit()
    return {"message": message, "status": "queued"}


def send_message(db: Session, *, charge_id: str, tenant_id: str, actor: str, text: str) -> dict:
    """Mensagem MANUAL (sem IA) ao cliente da cobrança.

    Fica de FORA da conversão para template: é texto arbitrário digitado por um humano, e um
    template não pode "envelopar" conteúdo livre (é exatamente o que a revisão da Meta existe para
    impedir — usar um template como disfarce arriscaria o rating de qualidade/ban do número). Este
    é o caso de "resposta dentro da janela de 24h": a própria Graph API da Meta aceita ou rejeita o
    envio conforme o estado real da conversa — não precisamos (nem podemos) simular isso aqui.
    Só passamos a usar as credenciais REAIS do tenant em vez do env global (sempre vazio agora).
    """
    text = (text or "").strip()
    if not text:
        raise ReceivableError("Mensagem vazia", 400)
    charge = get_charge(db, charge_id)
    client = db.get(Client, charge.client_id) if charge.client_id else None
    recipient = (client.phone if client and client.phone else None) or (
        client.name if client else "cliente"
    )
    notifications_service.enqueue(
        db, tenant_id=tenant_id, channel="whatsapp", recipient=recipient,
        client_id=charge.client_id, message=text, purpose=PURPOSE_CHARGE_REMINDER,
    )
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="receivable.message", target=charge.id
    )
    db.commit()
    return {"message": text, "status": "queued"}


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
    today = _today(db)
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
    # [8.15] `scheduled_cents` — e ele **não se mistura com nada** (AC7).
    #
    # Fica FORA de `open_cents`/`overdue_cents` (que exigem `STATUS_OPEN` — uma cobrança agendada
    # não está "a vencer" nem vencida: ela já tem dia marcado) e FORA de `paid_cents` (o dinheiro
    # ainda não caiu). Sem este campo, a cobrança agendada **desapareceria dos três buckets** — o
    # mesmo modo de falha "o dinheiro some da tela" que esta onda existe para eliminar, numa
    # superfície que o Cockpit e a Ficha 360° já consomem.
    #
    # O `_not_investment_yield()` vai junto pelo mesmo motivo de `paid_cents`: este resumo é
    # reconciliação de recebíveis de CLIENTE. Hoje a `Charge` de rendimento nasce `paid` e nunca
    # chega a `scheduled`, então o predicado é defensivo — e é assim que ele deve ficar, porque a
    # Onda 2b dá perna bancária ao rendimento e a ausência do filtro só apareceria lá.
    scheduled = db.scalar(
        select(func.coalesce(func.sum(Charge.amount_cents), 0))
        .where(Charge.status == STATUS_SCHEDULED)
        .where(_not_investment_yield())
    ) or 0
    return {
        "open_cents": open_cents,
        "overdue_cents": sum(c.amount_cents for c in overdue),
        "paid_cents": paid,
        "open_count": len([c for c in open_charges if c.due_date >= today]),
        "overdue_count": len(overdue),
        "scheduled_cents": int(scheduled),
    }
