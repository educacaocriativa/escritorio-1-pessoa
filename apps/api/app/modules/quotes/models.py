"""Central de Orçamentos.

Status: draft -> sent -> approved/rejected. Ao aprovar, dispara o "efeito dominó":
gera uma cobrança (Contas a Receber) para o valor total. Tabela de NEGÓCIO (RLS).
Dinheiro em centavos. Itens guardados como JSON [{description, quantity, unit_price_cents}].
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import JSON, BigInteger, Date, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

STATUS_DRAFT = "draft"
STATUS_SENT = "sent"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
ALL_STATUSES = {STATUS_DRAFT, STATUS_SENT, STATUS_APPROVED, STATUS_REJECTED}


class Quote(Base, TenantMixin, TimestampMixin):
    __tablename__ = "quotes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    client_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    items: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    discount_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    subtotal_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default=STATUS_DRAFT, nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # preenchido quando aprovado (efeito dominó -> cobrança)
    charge_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
