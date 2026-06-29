"""Central de Orçamentos — construtor de propostas (estilo Super Membros).

Quote = tabela de NEGÓCIO (RLS): os dados do editor (serviços, dados do cliente,
galeria, cronograma, contrato, aparência) + ciclo de status. Ao aprovar dispara o
"efeito dominó" (gera cobrança em Contas a Receber).

PublishedProposal = tabela GLOBAL (SEM RLS): snapshot público da proposta para o link
que o cliente abre sem login. RLS bloquearia leitura anônima de `quotes`; por isso o
snapshot é copiado para esta tabela ao salvar/enviar. Só dados de exibição ficam aqui.

Dinheiro em centavos. Itens: JSON [{description, subtitle, quantity, unit_price_cents}].
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import JSON, BigInteger, Boolean, Date, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

STATUS_DRAFT = "draft"
STATUS_SENT = "sent"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
ALL_STATUSES = {STATUS_DRAFT, STATUS_SENT, STATUS_APPROVED, STATUS_REJECTED}

DEFAULT_PRIMARY = "#5D44F8"
DEFAULT_BG = "#FFFFFF"
DEFAULT_TEXT = "#1F2937"
DEFAULT_ACCENT = "#3DD68C"


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

    # Dados (aba)
    client_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    client_whatsapp: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    payment_terms: Mapped[str] = mapped_column(Text, default="", nullable=False)
    link_password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Imagens (aba)
    show_gallery: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    gallery: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # Cronograma (aba)
    show_schedule: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    schedule: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # Contrato (aba)
    show_contract: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    contract_text: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # Aparência (aba)
    logo_url: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    primary_color: Mapped[str] = mapped_column(String(9), default=DEFAULT_PRIMARY, nullable=False)
    bg_color: Mapped[str] = mapped_column(String(9), default=DEFAULT_BG, nullable=False)
    text_color: Mapped[str] = mapped_column(String(9), default=DEFAULT_TEXT, nullable=False)
    accent_color: Mapped[str] = mapped_column(String(9), default=DEFAULT_ACCENT, nullable=False)

    # Link público
    public_slug: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)

    # preenchido quando aprovado (efeito dominó -> cobrança)
    charge_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class PublishedProposal(Base, TimestampMixin):
    """Snapshot público (GLOBAL, sem RLS) para o link que o cliente abre sem login."""

    __tablename__ = "published_proposals"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    quote_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
