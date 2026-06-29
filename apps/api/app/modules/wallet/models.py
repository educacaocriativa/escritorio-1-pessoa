"""Carteira & Split de Pagamentos (monetização e1p).

Cada venda vira uma Transaction (visão do usuário, RLS) com o split aplicado, e também uma
PlatformEarning (registro GLOBAL, sem RLS) para o painel de ganhos do Master.

DINHEIRO SEMPRE EM CENTAVOS INTEIROS (nunca float).
"""
from __future__ import annotations

from sqlalchemy import BigInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

# Tipo da venda → define a taxa de split retida pela plataforma.
KIND_PRODUCT = "product"  # 40% plataforma / 60% usuário
KIND_SERVICE = "service"  # 30% plataforma / 70% usuário
KIND_RECURRING = "recurring"  # 20% plataforma / 80% usuário
ALL_KINDS = {KIND_PRODUCT, KIND_SERVICE, KIND_RECURRING}

# Numerador/denominador da taxa da PLATAFORMA por tipo (split definido na spec).
SPLIT_RATES: dict[str, tuple[int, int]] = {
    KIND_PRODUCT: (40, 100),
    KIND_SERVICE: (30, 100),
    KIND_RECURRING: (20, 100),
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
