"""Rotas do módulo bancário: contas (Story 8.2) e movimentos (Story 8.3).

Sem `DELETE` em nenhuma das duas — de propósito. Conta encerrada é **arquivada** (AC2 da 8.2) e
movimento errado é **editado ou ignorado** (AC6 da 8.3): o histórico é o produto, e apagar
destruiria justamente a evidência que torna o saldo conferível.

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
from app.modules.bank.models import BankAccount, BankTransaction
from app.modules.bank.schemas import (
    BankAccountCreate,
    BankAccountOut,
    BankAccountUpdate,
    BankBalanceOut,
    BankTransactionCreate,
    BankTransactionOut,
    BankTransactionUpdate,
    IgnoreRequest,
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


def _tx_out(t: BankTransaction) -> BankTransactionOut:
    return BankTransactionOut(
        id=t.id,
        bank_account_id=t.bank_account_id,
        posted_at=t.posted_at,
        amount_cents=t.amount_cents,
        raw_description=t.raw_description,
        user_description=t.user_description,
        # A regra de exibição resolvida UMA vez, aqui — a UI da 8.7 não a reimplementa.
        description=t.user_description or t.raw_description,
        counterparty_name=t.counterparty_name,
        counterparty_document=t.counterparty_document,
        operation_nature=t.operation_nature,
        source=t.source,
        status=t.status,
        ignored_reason=t.ignored_reason,
        created_at=t.created_at,
        updated_at=t.updated_at,
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


# ── Movimentos (Story 8.3) ───────────────────────────────────────────────────────────────────


@router.post(
    "/accounts/{account_id}/transactions", response_model=BankTransactionOut, status_code=201
)
def create_transaction(
    account_id: str,
    data: BankTransactionCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankTransactionOut:
    """Lança um movimento MANUAL nesta conta. A conta vem do path; `source` é fixado no service."""
    try:
        tx = service.create_transaction(
            db,
            bank_account_id=account_id,
            tenant_id=user.tenant_id,
            actor=user.user_id,
            data=data,
        )
    except service.BankError as e:
        raise _err(e) from e
    return _tx_out(tx)


@router.get("/transactions", response_model=list[BankTransactionOut])
def list_transactions(
    bank_account_id: str | None = Query(default=None),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    # Repetível (`?status=unmatched&status=partial`): é o formato que a Story 8.5 precisa para
    # pedir "o que ainda não bateu" numa chamada só.
    status: list[str] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[BankTransactionOut]:
    """Movimentos do tenant, `posted_at` desc. `start`/`end` são inclusivos nas duas pontas."""
    try:
        rows = service.list_transactions(
            db,
            bank_account_id=bank_account_id,
            start=start,
            end=end,
            statuses=status,
            limit=limit,
            offset=offset,
        )
    except service.BankError as e:
        raise _err(e) from e
    return [_tx_out(t) for t in rows]


@router.get("/transactions/{transaction_id}", response_model=BankTransactionOut)
def get_transaction(
    transaction_id: str,
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankTransactionOut:
    try:
        return _tx_out(service.get_transaction(db, transaction_id))
    except service.BankError as e:
        raise _err(e) from e


@router.patch("/transactions/{transaction_id}", response_model=BankTransactionOut)
def update_transaction(
    transaction_id: str,
    data: BankTransactionUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankTransactionOut:
    """Corrige data, valor ou rótulo. `raw_description` NÃO é editável (invariante do modelo)."""
    try:
        tx = service.update_transaction(
            db,
            transaction_id=transaction_id,
            tenant_id=user.tenant_id,
            actor=user.user_id,
            data=data,
        )
    except service.BankError as e:
        raise _err(e) from e
    return _tx_out(tx)


@router.post("/transactions/{transaction_id}/ignore", response_model=BankTransactionOut)
def ignore_transaction(
    transaction_id: str,
    data: IgnoreRequest | None = None,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankTransactionOut:
    """Tira do saldo sem apagar. Idempotente. Corpo opcional (`{"reason": "..."}`)."""
    try:
        tx = service.ignore_transaction(
            db,
            transaction_id=transaction_id,
            tenant_id=user.tenant_id,
            actor=user.user_id,
            reason=(data.reason if data else ""),
        )
    except service.BankError as e:
        raise _err(e) from e
    return _tx_out(tx)


@router.post("/transactions/{transaction_id}/unignore", response_model=BankTransactionOut)
def unignore_transaction(
    transaction_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankTransactionOut:
    """Devolve ao saldo (`ignored` → `unmatched`). Idempotente."""
    try:
        tx = service.unignore_transaction(
            db, transaction_id=transaction_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.BankError as e:
        raise _err(e) from e
    return _tx_out(tx)
