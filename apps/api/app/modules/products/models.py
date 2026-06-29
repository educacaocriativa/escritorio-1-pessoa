"""Produtos & Checkout (estilo Super Membros): Produtos, Cupons e Alunos.

Vender um produto cria uma Transaction na Carteira (com split de produto) e matricula o Aluno.
Tabelas de NEGÓCIO (RLS). Dinheiro em centavos.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Boolean, Date, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

# Tipo do produto
KIND_PHYSICAL = "physical"  # produto físico (estoque)
KIND_DIGITAL = "digital"  # infoproduto (arquivo/link)
KIND_MEMBERSHIP = "membership"  # área de membros / curso
ALL_KINDS = {KIND_PHYSICAL, KIND_DIGITAL, KIND_MEMBERSHIP}

# Tipo do desconto do cupom
DISCOUNT_PERCENT = "percent"
DISCOUNT_FIXED = "fixed"
ALL_DISCOUNTS = {DISCOUNT_PERCENT, DISCOUNT_FIXED}

ENROLL_ACTIVE = "active"
ENROLL_CANCELED = "canceled"


class Product(Base, TenantMixin, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    price_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Estoque (só p/ físico). None = ilimitado/não controla.
    stock: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Coupon(Base, TenantMixin, TimestampMixin):
    __tablename__ = "coupons"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_coupon_tenant_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    discount_type: Mapped[str] = mapped_column(String(8), nullable=False)
    discount_value: Mapped[int] = mapped_column(Integer, nullable=False)  # % ou centavos
    product_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # None = qualquer
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    uses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)


class Enrollment(Base, TenantMixin, TimestampMixin):
    """Aluno/comprador de um produto."""

    __tablename__ = "enrollments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    product_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default=ENROLL_ACTIVE, nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)  # quanto pagou
    transaction_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
