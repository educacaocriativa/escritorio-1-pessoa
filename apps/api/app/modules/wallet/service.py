"""Regras da Carteira & Split: cálculo do split, transações, saldos e ganhos da plataforma."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit
from app.modules.wallet.models import (
    METHOD_CARD,
    SPLIT_RATES,
    STATUS_AVAILABLE,
    STATUS_PENDING,
    STATUS_REFUNDED,
    STATUS_WITHDRAWN,
    PlatformEarning,
    Transaction,
)
from app.modules.wallet.schemas import TransactionCreate


class WalletError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def compute_split(kind: str, gross_cents: int) -> tuple[int, int]:
    """Retorna (taxa_plataforma, liquido_usuario) em centavos. Arredonda meio-para-cima.

    Tudo em inteiro — nunca float. A taxa é a parte da plataforma (40/30/20).
    """
    numer, denom = SPLIT_RATES[kind]
    fee = (gross_cents * numer + denom // 2) // denom
    net = gross_cents - fee
    return fee, net


def create_transaction(
    db: Session, *, tenant_id: str, actor: str, by_ai: bool, data: TransactionCreate
) -> Transaction:
    fee, net = compute_split(data.kind, data.gross_cents)
    # Cartão entra como "a receber" (a liberar); Pix/boleto já caem como disponível.
    status = STATUS_PENDING if data.method == METHOD_CARD else STATUS_AVAILABLE

    tx = Transaction(
        tenant_id=tenant_id,
        kind=data.kind,
        method=data.method,
        description=data.description,
        gross_cents=data.gross_cents,
        platform_fee_cents=fee,
        net_cents=net,
        status=status,
        client_id=data.client_id,
        external_ref=data.external_ref,
    )
    db.add(tx)
    # Registro GLOBAL do ganho da plataforma (sem RLS) — alimenta o painel do Master.
    db.add(
        PlatformEarning(
            tenant_id=tenant_id, kind=data.kind, gross_cents=data.gross_cents, fee_cents=fee
        )
    )
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="wallet.transaction.create",
        target=tx.id, is_ai=by_ai,
    )
    db.commit()
    db.refresh(tx)
    return tx


def _sum_net(db: Session, status: str) -> int:
    return db.scalar(
        select(func.coalesce(func.sum(Transaction.net_cents), 0)).where(
            Transaction.status == status
        )
    ) or 0


def wallet_summary(db: Session) -> dict:
    gross = db.scalar(
        select(func.coalesce(func.sum(Transaction.gross_cents), 0)).where(
            Transaction.status != STATUS_REFUNDED
        )
    ) or 0
    fees = db.scalar(
        select(func.coalesce(func.sum(Transaction.platform_fee_cents), 0)).where(
            Transaction.status != STATUS_REFUNDED
        )
    ) or 0
    return {
        "available_cents": _sum_net(db, STATUS_AVAILABLE),
        "pending_cents": _sum_net(db, STATUS_PENDING),
        "withdrawn_cents": _sum_net(db, STATUS_WITHDRAWN),
        "gross_total_cents": gross,
        "fees_total_cents": fees,
    }


def list_transactions(db: Session, *, limit: int = 100, offset: int = 0) -> list[Transaction]:
    limit = max(1, min(limit, 500))
    stmt = (
        select(Transaction)
        .order_by(Transaction.created_at.desc())
        .limit(limit)
        .offset(max(0, offset))
    )
    return list(db.scalars(stmt).all())


def settle(db: Session, *, tx_id: str, tenant_id: str, actor: str) -> Transaction:
    """Simula a baixa do cartão: 'a receber' -> 'disponível'."""
    # FOR UPDATE serializa chamadas concorrentes (no-op no SQLite dos testes).
    tx = db.scalar(select(Transaction).where(Transaction.id == tx_id).with_for_update())
    if tx is None:
        raise WalletError("Transação não encontrada", 404)
    if tx.status != STATUS_PENDING:
        raise WalletError("Só transações 'a receber' podem ser liberadas", 409)
    tx.status = STATUS_AVAILABLE
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="wallet.transaction.settle", target=tx.id
    )
    db.commit()
    db.refresh(tx)
    return tx


def request_payout(db: Session, *, tenant_id: str, actor: str) -> dict:
    """Saca todo o saldo disponível (marca como sacado). Integração bancária/KYC: pendente.

    FOR UPDATE trava as linhas para evitar saque em dobro em chamadas concorrentes
    (no-op no SQLite dos testes; real no Postgres).
    """
    txs = list(
        db.scalars(
            select(Transaction).where(Transaction.status == STATUS_AVAILABLE).with_for_update()
        ).all()
    )
    total = sum(t.net_cents for t in txs)
    for t in txs:
        t.status = STATUS_WITHDRAWN
    audit.record(db, tenant_id=tenant_id, actor=actor, action="wallet.payout", target=str(total))
    db.commit()
    return {"amount_cents": total, "transactions": len(txs)}


# ── Visão do Master (global, sem RLS) ──────────────────


def platform_earnings(db: Session) -> dict:
    gmv = db.scalar(select(func.coalesce(func.sum(PlatformEarning.gross_cents), 0))) or 0
    fees = db.scalar(select(func.coalesce(func.sum(PlatformEarning.fee_cents), 0))) or 0
    count = db.scalar(select(func.count(PlatformEarning.id))) or 0
    fee_sum = func.coalesce(func.sum(PlatformEarning.fee_cents), 0)
    by_kind_rows = db.execute(
        select(PlatformEarning.kind, fee_sum).group_by(PlatformEarning.kind)
    ).all()
    return {
        "gmv_cents": gmv,
        "fees_cents": fees,
        "transaction_count": count,
        "by_kind": {kind: fee for kind, fee in by_kind_rows},
    }
