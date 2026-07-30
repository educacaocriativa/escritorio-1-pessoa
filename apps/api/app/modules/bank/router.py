"""Rotas da conta bancária (Story 8.2).

Sem `DELETE` — de propósito (AC2): conta encerrada é **arquivada**, nunca apagada, porque o
histórico de movimentos depende dela e a auditoria é o produto.

Toda rota usa `get_tenant_db` (RLS). Este módulo **não** entra na allowlist de
`tests/test_tenancy_guard.py`: não existe superfície pública aqui, e não deve passar a existir.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.money_planes import ORIGEM_BANCO
from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.bank import service
from app.modules.bank.models import BankAccount
from app.modules.bank.schemas import (
    BankAccountCreate,
    BankAccountOut,
    BankAccountUpdate,
    BankBalanceOut,
)

router = APIRouter(prefix="/bank", tags=["bank"])

_guard = require_module("bank")


def _out(a: BankAccount, saldo_derivado_cents: int) -> BankAccountOut:
    return BankAccountOut(
        id=a.id,
        name=a.name,
        kind=a.kind,
        institution=a.institution,
        institution_code=a.institution_code,
        branch=a.branch,
        number=a.number,
        holder_document=a.holder_document,
        pix_key=a.pix_key,
        opening_balance_cents=a.opening_balance_cents,
        opening_date=a.opening_date,
        is_primary=a.is_primary,
        archived_at=a.archived_at,
        saldo_derivado_cents=saldo_derivado_cents,
        # Constante do vocabulário do eixo A (`app.core.money_planes`) — nunca a string "banco"
        # escrita à mão. Todo saldo declara o plano de onde vem (Regra dos Planos §1.3c).
        saldo_derivado_origem=ORIGEM_BANCO,
        created_at=a.created_at,
    )


def _err(e: service.BankError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/accounts", response_model=list[BankAccountOut])
def list_accounts(
    include_archived: bool = Query(default=False),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[BankAccountOut]:
    """Lista as contas com o saldo derivado de HOJE (uma data só para todas).

    Este é o consumidor legítimo de `derived_balances_as_of` (design §3.1.1): tela de lista, data
    comum. A conferência (Story 8.5) **não** pode usar essa função — ver a docstring dela.
    """
    accounts = service.list_accounts(db, include_archived=include_archived)
    # Duas leituras baratas (as contas + os saldos em lote) em vez de 1 + N: a partir da Story 8.3
    # cada `derived_balance` avulso custaria um `SUM` próprio, e é esse N+1 que a função em lote
    # existe para evitar.
    balances = service.derived_balances_as_of(db, include_archived=include_archived)
    return [_out(a, balances.get(a.id, a.opening_balance_cents)) for a in accounts]


@router.post("/accounts", response_model=BankAccountOut, status_code=201)
def create_account(
    data: BankAccountCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankAccountOut:
    try:
        acc = service.create_account(db, tenant_id=user.tenant_id, actor=user.user_id, data=data)
        return _out(acc, service.derived_balance(db, bank_account_id=acc.id))
    except service.BankError as e:
        raise _err(e) from e


@router.get("/accounts/{account_id}", response_model=BankAccountOut)
def get_account(
    account_id: str,
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankAccountOut:
    try:
        acc = service.get_account(db, account_id)
        return _out(acc, service.derived_balance(db, bank_account_id=acc.id))
    except service.BankError as e:
        raise _err(e) from e


@router.patch("/accounts/{account_id}", response_model=BankAccountOut)
def update_account(
    account_id: str,
    data: BankAccountUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankAccountOut:
    try:
        acc = service.update_account(
            db, account_id=account_id, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
        return _out(acc, service.derived_balance(db, bank_account_id=acc.id))
    except service.BankError as e:
        raise _err(e) from e


@router.post("/accounts/{account_id}/archive", response_model=BankAccountOut)
def archive_account(
    account_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankAccountOut:
    try:
        acc = service.archive_account(
            db, account_id=account_id, tenant_id=user.tenant_id, actor=user.user_id
        )
        return _out(acc, service.derived_balance(db, bank_account_id=acc.id))
    except service.BankError as e:
        raise _err(e) from e


@router.get("/accounts/{account_id}/balance", response_model=BankBalanceOut)
def account_balance(
    account_id: str,
    until: date | None = Query(default=None),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankBalanceOut:
    """Saldo derivado desta conta até `until` (inclusivo; `None` = todo o histórico).

    `until` volta no payload: um saldo sem a data em que foi apurado é um número que não dá para
    conferir — e conferir é o produto (design §5.1).
    """
    try:
        saldo = service.derived_balance(db, bank_account_id=account_id, until=until)
    except service.BankError as e:
        raise _err(e) from e
    return BankBalanceOut(
        saldo_derivado_cents=saldo, saldo_derivado_origem=ORIGEM_BANCO, until=until
    )
