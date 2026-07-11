"""Construtor de Contratos + Assinatura & KYC.

ContractTemplate = modelo reutilizável (lista de cláusulas com variáveis [CLIENTE], [VALOR]...).
Contract = instância (cláusulas já preenchidas) com ciclo de status e dados da assinatura.
PublishedContract = snapshot GLOBAL (sem RLS) para o link de assinatura que o cliente abre
sem login (mesmo padrão das propostas públicas).

Cláusulas: JSON [{title, text}] — ordenáveis (drag-and-drop no editor).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

STATUS_DRAFT = "draft"
STATUS_SENT = "sent"
STATUS_SIGNED = "signed"
STATUS_CANCELLED = "cancelled"
ALL_STATUSES = {STATUS_DRAFT, STATUS_SENT, STATUS_SIGNED, STATUS_CANCELLED}


class ContractTemplate(Base, TenantMixin, TimestampMixin):
    __tablename__ = "contract_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    clauses: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


class Contract(Base, TenantMixin, TimestampMixin):
    __tablename__ = "contracts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    client_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    quote_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    clauses: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default=STATUS_DRAFT, nullable=False)
    public_slug: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)

    # Custo fixo atribuído ao contrato/projeto (Story 5.4), em centavos. Entrada MANUAL opcional
    # do usuário, usada no break-even da DRE do contrato. Distinta do rateio de overhead (que é
    # calculado só na leitura, nunca gravado). NULL = sem custo fixo atribuído (tratado como 0).
    fixed_costs_allocated_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Assinatura & KYC (preenchidos no aceite do cliente)
    signer_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    signer_document: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    signer_ip: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PublishedContract(Base, TimestampMixin):
    """Snapshot público (GLOBAL, sem RLS) do contrato para o link de assinatura."""

    __tablename__ = "published_contracts"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    contract_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
