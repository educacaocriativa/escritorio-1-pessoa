"""Controle de Estoque — itens + movimentações (ledger).

StockItem: item com quantidade, custo e mínimo (para alertas). Pode ligar a um Produto
(product_id) para baixa automática na venda. StockMovement: cada entrada/saída registrada.
Tabelas de NEGÓCIO (RLS). Dinheiro (custo) em centavos.
"""
from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

REASON_PURCHASE = "purchase"  # entrada (compra/reposição)
REASON_SALE = "sale"          # saída por venda
REASON_ADJUST = "adjust"      # ajuste manual
REASON_LOSS = "loss"          # perda/quebra
ALL_REASONS = {REASON_PURCHASE, REASON_SALE, REASON_ADJUST, REASON_LOSS}


class StockItem(Base, TenantMixin, TimestampMixin):
    __tablename__ = "stock_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    product_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unit_cost_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    min_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unit: Mapped[str] = mapped_column(String(12), default="un", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class StockMovement(Base, TenantMixin, TimestampMixin):
    __tablename__ = "stock_movements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    item_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)  # + entrada / - saída
    reason: Mapped[str] = mapped_column(String(12), nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
