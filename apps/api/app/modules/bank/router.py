"""Rotas do módulo bancário: contas (8.2), movimentos (8.3) e saldos declarados (8.4).

Sem `DELETE` em conta nem em movimento — de propósito. Conta encerrada é **arquivada** (AC2 da 8.2)
e movimento errado é **editado ou ignorado** (AC6 da 8.3): o histórico é o produto, e apagar
destruiria justamente a evidência que torna o saldo conferível. O **checkpoint** é a única exceção
(`DELETE /bank/checkpoints/{id}`) — ele não tem histórico dependente; ver o porquê em
`service.delete_checkpoint`.

**Vocabulário voltado ao usuário:** *"saldo desta conta no fim do dia"*, dentro do menu
**"Contas & Saldos"** (design §5.4). O rótulo *"conciliação bancária"* é **proibido** pelo epic §2.1
— ele descreve um trabalho de contador, e este produto pede 5 segundos de confirmação por mês.

Toda rota usa `get_tenant_db` (RLS). Este módulo **não** entra na allowlist de
`tests/test_tenancy_guard.py`: não existe superfície pública aqui, e não deve passar a existir.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.money_planes import ORIGEM_BANCO
from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.bank import service
from app.modules.bank.models import BankAccount, BankBalanceCheckpoint, BankTransaction
from app.modules.bank.schemas import (
    BankAccountCreate,
    BankAccountOut,
    BankAccountUpdate,
    BankBalanceOut,
    BankTransactionCreate,
    BankTransactionOut,
    BankTransactionUpdate,
    CheckpointCreate,
    CheckpointOut,
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


def _cp_out(c: BankBalanceCheckpoint) -> CheckpointOut:
    return CheckpointOut(
        id=c.id,
        bank_account_id=c.bank_account_id,
        reference_date=c.reference_date,
        balance_cents=c.balance_cents,
        # Eixo A (plano) do saldo declarado — constante do vocabulário de `app.core.money_planes`,
        # nunca a string "banco" à mão. O saldo que o usuário leu no app do banco é plano 3, e é
        # por os dois números serem do MESMO plano que compará-los na 8.5 faz sentido.
        balance_origem=ORIGEM_BANCO,
        # Eixo B (porta de entrada) do mesmo saldo. Não se traduz no eixo A — design §1.3.1.
        origin=c.origin,
        created_by=c.created_by,
        created_at=c.created_at,
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


# ── Saldos declarados (Story 8.4) ────────────────────────────────────────────────────────────


@router.post(
    "/accounts/{account_id}/checkpoints", response_model=CheckpointOut, status_code=201
)
def declare_balance(
    account_id: str,
    data: CheckpointCreate,
    response: Response,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> CheckpointOut:
    """Informa o saldo desta conta **no fim** do dia `reference_date`.

    **201** quando é a primeira declaração daquele dia; **200** quando corrige uma existente — o
    mesmo dia declarado de novo **corrige**, nunca conflita (AC4): quem digitou o número errado
    precisa de um gesto para arrumar, não de um ciclo apagar→recriar.

    Este número **não** altera o saldo que o e1p calculou; ele é a verdade externa contra a qual
    esse saldo é medido. A comparação entre os dois é a Story 8.5.
    """
    try:
        cp, criado = service.declare_balance(
            db,
            bank_account_id=account_id,
            tenant_id=user.tenant_id,
            actor=user.user_id,
            data=data,
        )
    except service.BankError as e:
        raise _err(e) from e
    if not criado:
        response.status_code = 200
    return _cp_out(cp)


@router.get("/accounts/{account_id}/checkpoints", response_model=list[CheckpointOut])
def list_checkpoints(
    account_id: str,
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[CheckpointOut]:
    """Saldos já informados desta conta, do mais recente para o mais antigo.

    Só a lista dos fatos declarados — **sem** histórico ou gráfico de saldo (fora do escopo,
    epic §6) e **sem** divergência (é a Story 8.5, que tem a banda de tolerância e a decomposição
    por conta que um número solto aqui não teria).
    """
    try:
        # A conta é validada mesmo numa leitura: pedir os saldos de uma conta que não existe (ou é
        # de outro tenant) tem que ser 404, não uma lista vazia — vazio significaria "esta conta
        # nunca teve saldo informado", que é uma afirmação diferente e enganosa.
        service.get_account(db, account_id)
        rows = service.list_checkpoints(
            db, bank_account_id=account_id, start=start, end=end, limit=limit, offset=offset
        )
    except service.BankError as e:
        raise _err(e) from e
    return [_cp_out(c) for c in rows]


@router.get("/checkpoints/{checkpoint_id}", response_model=CheckpointOut)
def get_checkpoint(
    checkpoint_id: str,
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> CheckpointOut:
    try:
        return _cp_out(service.get_checkpoint(db, checkpoint_id))
    except service.BankError as e:
        raise _err(e) from e


@router.delete("/checkpoints/{checkpoint_id}", status_code=204)
def delete_checkpoint(
    checkpoint_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> Response:
    """Remove uma declaração indevida. Único `DELETE` do módulo `bank`.

    O porquê de ele ser a exceção está em `service.delete_checkpoint`.
    """
    try:
        service.delete_checkpoint(
            db, checkpoint_id=checkpoint_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.BankError as e:
        raise _err(e) from e
    return Response(status_code=204)
