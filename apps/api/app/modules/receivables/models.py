"""Contas a Receber — cobranças (boleto/Pix/link).

Quando uma cobrança é paga, vira uma Transaction na Carteira (com o split aplicado) e o
vencimento é injetado na Agenda. Tabela de NEGÓCIO (RLS).
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

# kind = tipo da venda (define o split quando paga): product/service/recurring (igual à wallet).
METHOD_PIX = "pix"
METHOD_BOLETO = "boleto"
METHOD_CARD = "card"
ALL_METHODS = {METHOD_PIX, METHOD_BOLETO, METHOD_CARD}

STATUS_OPEN = "open"
STATUS_PAID = "paid"
STATUS_CANCELED = "canceled"
ALL_STATUSES = {STATUS_OPEN, STATUS_PAID, STATUS_CANCELED}


class Charge(Base, TenantMixin, TimestampMixin):
    __tablename__ = "charges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    client_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # split quando paga: product/service/recurring
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[str] = mapped_column(String(12), default=STATUS_OPEN, nullable=False)
    # Stub do gateway: Pix copia-e-cola / linha do boleto / link de pagamento.
    payment_code: Mapped[str] = mapped_column(Text, default="", nullable=False)
    transaction_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # tx da carteira
    # evento de vencimento na agenda
    agenda_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # quando protestada (cobrança vencida levada a protesto); None = não protestada
    protested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # recorrência: gera N cobranças (uma por vencimento) ligadas por recurrence_group
    recurrence: Mapped[str] = mapped_column(String(8), default="none", nullable=False)
    recurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    recurrence_group: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Gateway de pagamento real (Asaas). Nullable/aditivos (migration 0033): quando o gateway
    # está configurado, guardam qual provedor gerou a cobrança, o id dela no provedor (suporte)
    # e o último status bruto recebido pelo webhook (debug). None = cobrança via stub.
    gateway_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    gateway_charge_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gateway_status_raw: Mapped[str | None] = mapped_column(String(40), nullable=True)
