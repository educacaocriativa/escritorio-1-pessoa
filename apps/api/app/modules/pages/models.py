"""Sites / Páginas — construtor de landing pages.

Page = página editável (RLS) com blocos (heading/text/image/button/form/video/divider),
modelo (vendas/captura/...) e estilo (herda o Brand Kit). PublishedPage = snapshot GLOBAL
(sem RLS) para a página pública que o visitante abre sem login (mesmo padrão das propostas).
Formulário de captura vira lead no CRM.
"""
from __future__ import annotations

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

STATUS_DRAFT = "draft"
STATUS_PUBLISHED = "published"


class Page(Base, TenantMixin, TimestampMixin):
    __tablename__ = "pages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    model: Mapped[str] = mapped_column(String(24), default="conteudo", nullable=False)
    blocks: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default=STATUS_DRAFT, nullable=False)
    public_slug: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)

    # Estilo (herda o Brand Kit do tenant)
    primary_color: Mapped[str] = mapped_column(String(9), default="#5D44F8", nullable=False)
    bg_color: Mapped[str] = mapped_column(String(9), default="#FFFFFF", nullable=False)
    text_color: Mapped[str] = mapped_column(String(9), default="#1F2937", nullable=False)
    accent_color: Mapped[str] = mapped_column(String(9), default="#3DD68C", nullable=False)
    font: Mapped[str] = mapped_column(String(40), default="Inter", nullable=False)
    logo_url: Mapped[str] = mapped_column(String(1024), default="", nullable=False)


class PublishedPage(Base, TimestampMixin):
    """Snapshot público (GLOBAL, sem RLS) da página publicada."""

    __tablename__ = "published_pages"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    page_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
