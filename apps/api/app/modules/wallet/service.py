"""Regras da Carteira & Split: cálculo do split, transações, saldos e ganhos da plataforma."""
from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit
from app.modules.chart_of_accounts import service as chart_service
from app.modules.cost_centers import service as cost_centers_service
from app.modules.wallet.models import (
    DEFAULT_SPLIT_PCT,
    KIND_PRODUCT,
    KIND_RECURRING,
    KIND_SERVICE,
    METHOD_CARD,
    SETTINGS_ID,
    STATUS_AVAILABLE,
    STATUS_PENDING,
    STATUS_REFUNDED,
    STATUS_WITHDRAWN,
    PlatformEarning,
    PlatformSetting,
    Transaction,
)
from app.modules.wallet.schemas import TransactionCreate

# Limite de segurança: a plataforma nunca retém 100% (deixaria o usuário sem nada).
MAX_SPLIT_PCT = 95


class WalletError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def compute_split(gross_cents: int, platform_pct: int) -> tuple[int, int]:
    """Retorna (taxa_plataforma, liquido_usuario) em centavos. Arredonda meio-para-cima.

    Tudo em inteiro — nunca float. `platform_pct` é a % retida pela plataforma.
    """
    fee = (gross_cents * platform_pct + 50) // 100
    net = gross_cents - fee
    return fee, net


def get_settings(db: Session) -> PlatformSetting | None:
    return db.get(PlatformSetting, SETTINGS_ID)


def split_pct_for(db: Session, kind: str) -> int:
    """% retida pela plataforma para o tipo, lida da configuração do Master (ou padrão)."""
    s = get_settings(db)
    if s is None:
        return DEFAULT_SPLIT_PCT[kind]
    return {
        KIND_PRODUCT: s.split_product_pct,
        KIND_SERVICE: s.split_service_pct,
        KIND_RECURRING: s.split_recurring_pct,
    }[kind]


def current_rates(db: Session) -> dict:
    s = get_settings(db)
    if s is None:
        return {
            "product_pct": DEFAULT_SPLIT_PCT[KIND_PRODUCT],
            "service_pct": DEFAULT_SPLIT_PCT[KIND_SERVICE],
            "recurring_pct": DEFAULT_SPLIT_PCT[KIND_RECURRING],
        }
    return {
        "product_pct": s.split_product_pct,
        "service_pct": s.split_service_pct,
        "recurring_pct": s.split_recurring_pct,
    }


def update_split_rates(
    db: Session, *, product_pct: int, service_pct: int, recurring_pct: int
) -> dict:
    for pct in (product_pct, service_pct, recurring_pct):
        if pct < 0 or pct > MAX_SPLIT_PCT:
            raise WalletError(f"taxa inválida: use de 0 a {MAX_SPLIT_PCT}%")
    s = get_settings(db)
    if s is None:
        s = PlatformSetting(id=SETTINGS_ID)
        db.add(s)
    s.split_product_pct = product_pct
    s.split_service_pct = service_pct
    s.split_recurring_pct = recurring_pct
    db.commit()
    return current_rates(db)


def build_transaction(
    db: Session,
    *,
    tenant_id: str,
    actor: str,
    by_ai: bool,
    kind: str,
    method: str,
    gross_cents: int,
    description: str = "",
    client_id: str | None = None,
    external_ref: str | None = None,
    competence_date: date | None = None,
    chart_account_id: str | None = None,
    cost_center_id: str | None = None,
) -> Transaction:
    """Cria a transação + ganho da plataforma na sessão SEM commitar.

    Permite que outros módulos (ex.: Contas a Receber, ao dar baixa) gravem a transação
    atomicamente junto com sua própria mutação. Chamadores que já reconhecem a receita em outro
    lugar (ex.: Charge paga) não passam `chart_account_id`/`cost_center_id` — a classificação nessa
    origem é do Charge, e a DRE já exclui transações com `external_ref` preenchido para não somar
    em dobro (ver `financial_intelligence/dre.py`).
    """
    pct = split_pct_for(db, kind)
    fee, net = compute_split(gross_cents, pct)
    # Cartão entra como "a receber" (a liberar); Pix/boleto já caem como disponível.
    status = STATUS_PENDING if method == METHOD_CARD else STATUS_AVAILABLE

    if chart_account_id and not chart_service.exists(db, chart_account_id):
        raise WalletError("Conta do plano de contas não encontrada", 404)
    if cost_center_id and not cost_centers_service.exists(db, cost_center_id):
        raise WalletError("Centro de custo não encontrado", 404)

    tx = Transaction(
        tenant_id=tenant_id,
        kind=kind,
        method=method,
        description=description,
        gross_cents=gross_cents,
        platform_fee_cents=fee,
        net_cents=net,
        status=status,
        client_id=client_id,
        external_ref=external_ref,
        competence_date=competence_date or datetime.now(UTC).date(),
        chart_account_id=chart_account_id,
        cost_center_id=cost_center_id,
    )
    db.add(tx)
    # Registro GLOBAL do ganho da plataforma (sem RLS) — alimenta o painel do Master.
    db.add(PlatformEarning(tenant_id=tenant_id, kind=kind, gross_cents=gross_cents, fee_cents=fee))
    db.flush()  # popula tx.id (p/ a auditoria e p/ quem linka antes do commit)
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="wallet.transaction.create",
        target=tx.id, is_ai=by_ai,
    )
    return tx


def create_transaction(
    db: Session, *, tenant_id: str, actor: str, by_ai: bool, data: TransactionCreate
) -> Transaction:
    tx = build_transaction(
        db, tenant_id=tenant_id, actor=actor, by_ai=by_ai, kind=data.kind, method=data.method,
        gross_cents=data.gross_cents, description=data.description, client_id=data.client_id,
        external_ref=data.external_ref, competence_date=data.competence_date,
        chart_account_id=data.chart_account_id, cost_center_id=data.cost_center_id,
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
