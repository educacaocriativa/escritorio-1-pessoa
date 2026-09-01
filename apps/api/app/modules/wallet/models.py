"""Carteira & Split de Pagamentos (monetização e1p).

Cada venda vira uma Transaction (visão do usuário, RLS) com o split aplicado, e também uma
PlatformEarning (registro GLOBAL, sem RLS) para o painel de ganhos do Master.

DINHEIRO SEMPRE EM CENTAVOS INTEIROS (nunca float).
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

# Tipo da venda → define a taxa de split retida pela plataforma.
KIND_PRODUCT = "product"  # 40% plataforma / 60% usuário
KIND_SERVICE = "service"  # 30% plataforma / 70% usuário
KIND_RECURRING = "recurring"  # 20% plataforma / 80% usuário
ALL_KINDS = {KIND_PRODUCT, KIND_SERVICE, KIND_RECURRING}

# Taxa PADRÃO da plataforma (%) por tipo. O Master pode sobrescrever em PlatformSetting.
DEFAULT_SPLIT_PCT: dict[str, int] = {
    KIND_PRODUCT: 40,
    KIND_SERVICE: 30,
    KIND_RECURRING: 20,
}

METHOD_PIX = "pix"
METHOD_CARD = "card"
METHOD_BOLETO = "boleto"
ALL_METHODS = {METHOD_PIX, METHOD_CARD, METHOD_BOLETO}

STATUS_PENDING = "pending"  # cartão a liberar
STATUS_AVAILABLE = "available"  # disponível p/ saque
STATUS_WITHDRAWN = "withdrawn"
STATUS_REFUNDED = "refunded"
ALL_STATUSES = {STATUS_PENDING, STATUS_AVAILABLE, STATUS_WITHDRAWN, STATUS_REFUNDED}


class Transaction(Base, TenantMixin, TimestampMixin):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    gross_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)  # valor bruto pago
    platform_fee_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)  # split retido
    net_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)  # líquido p/ o usuário

    status: Mapped[str] = mapped_column(String(12), default=STATUS_AVAILABLE, nullable=False)
    client_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Classificação DRE (Story 5.10, aditivas/nullable — migration 0050; mesmo padrão de
    # payables/charges desde 5.1/5.2/5.5). competence_date: regime de COMPETÊNCIA (DRE); sem
    # `due_date` p/ dar fallback (a transação já é caixa realizado), então o service preenche com a
    # data de criação quando omitida — e a DRE ainda faz COALESCE(competence_date, created_at::date)
    # como rede de segurança para qualquer linha legada. chart_account_id/cost_center_id: vínculo
    # OPCIONAL (sem FK dura, mesmo padrão do projeto) — NULL = sem categoria / não atribuído.
    competence_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    chart_account_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cost_center_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Número/identificador do documento (nota fiscal, recibo...) — texto livre. Observações: nota
    # livre do dono sobre a venda.
    documento: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    observacoes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # Onda 3 — a qual saque esta venda pertence. NULL = ainda não sacada, **ou** sacada antes da
    # migration 0077 (não há backfill, e não pode haver: aqueles saques nunca foram registrados,
    # então não existe linha a que pertencer — a mesma manobra da 2b-ii).
    payout_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class Payout(Base, TenantMixin, TimestampMixin):
    """O saque da Carteira como **fato**, não como troca de status (Onda 3).

    Antes desta onda, `request_payout` virava N `Transaction` para `withdrawn`, gravava
    `audit.record(target=str(total))` — o VALOR, não um id — e não deixava linha nenhuma. O dono
    via o saldo sumir e não conseguia listar o que sacou, quando, nem para onde.

    Isso não era só lacuna de produto: `bank.origin.sync_origin_movement` exige `origin_id`
    apontando para *"o lançamento que o gerou"*, sob índice único 1:1. **Sem entidade não havia
    para onde apontar**, e o payout não podia virar movimento bancário como as outras quatro
    origens já viraram.

    ⚠️ **`bank_account_id` é SNAPSHOT, não referência viva.** A conta principal pode mudar depois;
    o saque de agosto não pode passar a dizer que caiu na conta que virou principal em outubro.

    ⚠️ **`bank_transaction_id` é `NOT NULL`, e a diferença para os irmãos é deliberada.** Em
    `payable.bank_transaction_id` / `charge.bank_transaction_id` a coluna é nullable porque o
    lançamento pode legitimamente ainda não estar liquidado. **Payout não liquidado não existe** —
    o caminho de código não tem ramo que crie um sem destino (ver `wallet/service.request_payout`).
    Não "harmonize" as três colunas: elas têm contratos diferentes.
    """

    __tablename__ = "payouts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_on: Mapped[date] = mapped_column(Date, nullable=False)
    bank_account_id: Mapped[str] = mapped_column(String(36), nullable=False)
    bank_transaction_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor: Mapped[str] = mapped_column(String(36), nullable=False)


SETTINGS_ID = "platform"  # singleton


class PlatformSetting(Base, TimestampMixin):
    """Configuração GLOBAL da plataforma (linha única). Editável só pelo Master.

    Guarda as taxas de split (% retido pela plataforma) por tipo de venda.
    """

    __tablename__ = "platform_settings"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=SETTINGS_ID)
    split_product_pct: Mapped[int] = mapped_column(Integer, default=40, nullable=False)
    split_service_pct: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    split_recurring_pct: Mapped[int] = mapped_column(Integer, default=20, nullable=False)


class PlatformEarning(Base, TimestampMixin):
    """Registro GLOBAL (sem RLS) do que a PLATAFORMA reteve. Só o Master agrega.

    Mantido mesmo após a exclusão de uma conta (retenção de registro financeiro).
    """

    __tablename__ = "platform_earnings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    gross_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
