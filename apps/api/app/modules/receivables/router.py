"""Rotas de Contas a Receber."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.db.session import get_tenant_session_factory
from app.modules.crm.models import Client
from app.modules.notifications.schemas import NotificationOut
from app.modules.receivables import service
from app.modules.receivables.models import Charge
from app.modules.receivables.schemas import (
    ChargeCreate,
    ChargeOut,
    ChargesSummary,
    ChargeUpdate,
    DunningResult,
    MessageRequest,
    RescheduleRequest,
)

router = APIRouter(prefix="/receivables", tags=["receivables"])

_guard = require_module("receivables")


def _out(charge: Charge, db: Session) -> ChargeOut:
    client = db.get(Client, charge.client_id) if charge.client_id else None
    return ChargeOut(
        id=charge.id,
        tenant_id=charge.tenant_id,
        client_id=charge.client_id,
        client_name=client.name if client else None,
        description=charge.description,
        kind=charge.kind,
        method=charge.method,
        amount_cents=charge.amount_cents,
        due_date=charge.due_date,
        competence_date=charge.competence_date,
        paid_at=charge.paid_at,
        chart_account_id=charge.chart_account_id,
        contract_id=charge.contract_id,
        cost_center_id=charge.cost_center_id,
        status=charge.status,
        is_overdue=service.is_overdue(charge),
        protested_at=charge.protested_at,
        recurrence=charge.recurrence,
        recurrence_group=charge.recurrence_group,
        payment_code=charge.payment_code,
        transaction_id=charge.transaction_id,
        created_at=charge.created_at,
        gateway_provider=charge.gateway_provider,
        gateway_status_raw=charge.gateway_status_raw,
    )


def _err(e: service.ReceivableError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


@router.post("/webhook")
def payment_webhook(
    body: dict = Body(...),
    asaas_access_token: str | None = Header(default=None),
    session_factory=Depends(get_tenant_session_factory),
) -> dict:
    """Webhook do gateway: reconhece o pagamento AUTOMATICAMENTE (sem login). Aceita o payload
    REAL do provedor (Asaas: {event, payment.externalReference}) OU o payload interno de dev/teste
    ({tenant_id, charge_id, status, secret}) — o link 'simular pgto' continua funcionando.

    Segurança (fail-closed): com GATEWAY_WEBHOOK_SECRET definido, só o gateway confirma — para o
    payload real valida o token do header (`asaas-access-token`), para o interno valida `secret`
    no corpo. Segredo vazio (dev) = aberto para testes. O dono NUNCA marca pago manualmente.

    Nota (No Invention): o nome do header de autenticação do Asaas deve ser confirmado contra a
    documentação vigente do provedor antes do go-live."""
    try:
        return service.process_webhook(
            session_factory=session_factory, body=body, token=asaas_access_token
        )
    except service.ReceivableError as e:
        raise _err(e) from e


@router.get("/summary", response_model=ChargesSummary)
def summary(
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ChargesSummary:
    return ChargesSummary(**service.summary(db))


@router.get("/charges", response_model=list[ChargeOut])
def list_charges(
    status: str | None = Query(default=None),
    client_id: str | None = Query(default=None),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[ChargeOut]:
    return [_out(c, db) for c in service.list_charges(db, status=status, client_id=client_id)]


@router.post("/charges", response_model=ChargeOut, status_code=201)
def create_charge(
    data: ChargeCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ChargeOut:
    try:
        charge = service.create_charge(db, tenant_id=user.tenant_id, actor=user.user_id, data=data)
    except service.ReceivableError as e:
        raise _err(e) from e
    return _out(charge, db)


@router.post("/charges/{charge_id}/pay", response_model=ChargeOut)
def pay_charge(
    charge_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ChargeOut:
    try:
        charge = service.mark_paid(
            db, charge_id=charge_id, tenant_id=user.tenant_id, actor=user.user_id, by_ai=user.is_ai
        )
    except service.ReceivableError as e:
        raise _err(e) from e
    return _out(charge, db)


@router.get("/charges/{charge_id}", response_model=ChargeOut)
def get_charge(
    charge_id: str,
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ChargeOut:
    try:
        return _out(service.get_charge(db, charge_id), db)
    except service.ReceivableError as e:
        raise _err(e) from e


@router.patch("/charges/{charge_id}", response_model=ChargeOut)
def update_charge(
    charge_id: str,
    data: ChargeUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ChargeOut:
    try:
        charge = service.update_charge(
            db, charge_id=charge_id, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
    except service.ReceivableError as e:
        raise _err(e) from e
    return _out(charge, db)


@router.get("/charges/{charge_id}/messages", response_model=list[NotificationOut])
def charge_messages(
    charge_id: str,
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[NotificationOut]:
    try:
        msgs = service.charge_messages(db, charge_id=charge_id)
    except service.ReceivableError as e:
        raise _err(e) from e
    return [NotificationOut.model_validate(m) for m in msgs]


@router.post("/charges/{charge_id}/message", response_model=DunningResult)
def send_message(
    charge_id: str,
    data: MessageRequest,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> DunningResult:
    try:
        result = service.send_message(
            db, charge_id=charge_id, tenant_id=user.tenant_id, actor=user.user_id, text=data.text
        )
    except service.ReceivableError as e:
        raise _err(e) from e
    return DunningResult(**result)


@router.post("/charges/{charge_id}/collect", response_model=DunningResult)
def collect_charge(
    charge_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> DunningResult:
    """A IA escreve e envia uma cobrança amigável ao cliente no WhatsApp."""
    try:
        result = service.collect_with_ai(
            db, charge_id=charge_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.ReceivableError as e:
        raise _err(e) from e
    return DunningResult(**result)


@router.post("/charges/{charge_id}/cancel", response_model=ChargeOut)
def cancel_charge(
    charge_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ChargeOut:
    try:
        charge = service.cancel_charge(
            db, charge_id=charge_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.ReceivableError as e:
        raise _err(e) from e
    return _out(charge, db)


@router.post("/charges/{charge_id}/reschedule", response_model=ChargeOut)
def reschedule_charge(
    charge_id: str,
    data: RescheduleRequest,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ChargeOut:
    try:
        charge = service.reschedule_charge(
            db, charge_id=charge_id, tenant_id=user.tenant_id, actor=user.user_id,
            due_date=data.due_date,
        )
    except service.ReceivableError as e:
        raise _err(e) from e
    return _out(charge, db)


@router.post("/charges/{charge_id}/protest", response_model=ChargeOut)
def protest_charge(
    charge_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ChargeOut:
    try:
        charge = service.protest_charge(
            db, charge_id=charge_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.ReceivableError as e:
        raise _err(e) from e
    return _out(charge, db)
