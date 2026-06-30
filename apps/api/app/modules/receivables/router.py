"""Rotas de Contas a Receber."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
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
    WebhookPayment,
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
        status=charge.status,
        is_overdue=service.is_overdue(charge),
        protested_at=charge.protested_at,
        recurrence=charge.recurrence,
        recurrence_group=charge.recurrence_group,
        payment_code=charge.payment_code,
        transaction_id=charge.transaction_id,
        created_at=charge.created_at,
    )


def _err(e: service.ReceivableError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


@router.post("/webhook")
def payment_webhook(
    data: WebhookPayment,
    session_factory=Depends(get_tenant_session_factory),
) -> dict:
    """Webhook do gateway: reconhece o pagamento AUTOMATICAMENTE (sem login). Em produção,
    defina GATEWAY_WEBHOOK_SECRET para que só o gateway confirme; em dev (segredo vazio) fica
    aberto para testes. O dono NUNCA marca pago manualmente — só saca o que entra por aqui."""
    if settings.gateway_webhook_secret and data.secret != settings.gateway_webhook_secret:
        raise HTTPException(status_code=401, detail="Segredo do webhook inválido")
    if data.status != "paid":
        return {"status": "ignored"}
    try:
        status = service.webhook_confirm(
            session_factory=session_factory, tenant_id=data.tenant_id, charge_id=data.charge_id
        )
    except service.ReceivableError as e:
        raise _err(e) from e
    return {"status": status}


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
    charge = service.create_charge(db, tenant_id=user.tenant_id, actor=user.user_id, data=data)
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
