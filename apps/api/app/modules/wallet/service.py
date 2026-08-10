"""Regras da Carteira & Split: cálculo do split, transações, saldos e ganhos da plataforma."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit
from app.modules.chart_of_accounts import service as chart_service
from app.modules.cost_centers import service as cost_centers_service
from app.modules.settings.service import hoje_do_tenant
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
    Payout,
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
        competence_date=competence_date or hoje_do_tenant(db),
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


# ── O ponto de contato entre o plano da PLATAFORMA e o plano do BANCO (Onda 3) ────────────────
#
# ⚠️ **Este é o ÚNICO write que atravessa a fronteira dos planos** (design-mãe §1.2), e ele é
# declarado AQUI, do lado da Carteira, sendo implementado por `bank/payout.py` e ligado em
# `app/main.py`. Mesmo padrão das duas travessias irmãs (guarda de contagem dupla, Story 8.17 AC6;
# termos do gate, Story 8.16 AC7/AC8): **quem precisa do serviço declara o `Protocol`; quem
# implementa não é importado por ninguém; a fiação mora na composição.**
#
# **O gate `test_wallet_nao_importa_bank` fica verde porque a dependência SUMIU, não porque foi
# escondida.** Se o seu código parece precisar de importar o módulo do banco aqui, o que falta é um
# parâmetro neste `Protocol`.
#
# ⚠️ E note que a frase acima **não escreve o caminho do módulo proibido**, nem em comentário: o
# gate irmão (`..._tambem_por_texto_cru`) é um `grep` literal, e ele reprova a menção em qualquer
# forma — inclusive esta. Isso é recurso, não bug. Um gate que abrisse exceção para comentários
# precisaria distinguir comentário de código, e a primeira string evasiva montada em runtime
# passaria por ele. Foi a mutação do re-gate da Onda 1 (TEST-001) que provou que os dois gates
# precisam existir e que nenhum dos dois pode ser "esperto".
#
# ⚠️ **Por que NÃO é `core/events` (o design-mãe §6.6 mandava).** `events.emit` engole exceção de
# assinante por contrato (*"o fato já aconteceu e foi commitado; reações são best-effort"*), e os
# dois assinantes existentes recebem o evento DEPOIS do commit. A Regra da Origem (a) exige o
# movimento na MESMA transação. Pelo barramento, um payout commitaria com a perna bancária
# faltando **e sem erro em lugar nenhum** — a família de defeito que o Epic 8 existe para eliminar.
# O §6.6 é anterior à Onda 2 e não sobrevive ao que ela estabeleceu.


@dataclass(frozen=True)
class DestinoDoPayout:
    """Para onde o saque foi — ou o **fato** que impediu.

    Três formas, e só três:

    - **sucesso:** os dois ids preenchidos, `recusa_detalhe is None`;
    - **sem conta principal:** o registrador devolve `None` (não esta dataclass). A frase é da
      Carteira, porque não contém dado nenhum do banco;
    - **o banco recusou o movimento** (hoje: data anterior à abertura da conta): `recusa_detalhe`
      traz a mensagem do próprio módulo `bank`, que já nomeia a data. A Carteira decide o status
      code e a moldura; o fato vem de quem o conhece.
    """

    bank_account_id: str | None = None
    bank_transaction_id: str | None = None
    recusa_detalhe: str | None = None


class RegistradorDePayout(Protocol):
    """Escreve a perna bancária do saque. Implementado por `bank/payout.py`. **NÃO commita.**

    Devolve `None` quando não há conta principal ativa — e isso é **valor de retorno, não
    exceção**, de propósito: assim o texto do 409 pertence à Carteira, que é quem tem o usuário na
    frente, e o módulo `bank` não precisa conhecer o vocabulário da tela do outro plano.
    """

    def __call__(
        self,
        db: Session,
        *,
        tenant_id: str,
        actor: str,
        payout_id: str,
        amount_cents: int,
        posted_at: date,
    ) -> DestinoDoPayout | None: ...


_payout_registrar: RegistradorDePayout | None = None


def register_payout_registrar(fn: RegistradorDePayout) -> None:
    """Chamado UMA vez, por `app/main.py`. Ver `verifica_fiacao_do_payout` lá."""
    global _payout_registrar
    _payout_registrar = fn


def payout_registrar_registrado() -> bool:
    return _payout_registrar is not None


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
