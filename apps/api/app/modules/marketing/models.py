"""Marketing / Redes Sociais — gerador de carrossel com templates personalizáveis.

Carousel = um post de carrossel (slides) com estilo próprio (cores/fonte/template), para
o usuário personalizar facilmente em cima do que a IA gera. Tabela de NEGÓCIO (RLS).
Slides: JSON [{heading, body}].
"""
from __future__ import annotations

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

STATUS_DRAFT = "draft"
STATUS_READY = "ready"

# Padrão editorial (estilo da skill do usuário): fundo escuro + acento roxo.
DEFAULT_PRIMARY = "#B078FF"
DEFAULT_BG = "#292A25"
DEFAULT_TEXT = "#FFFFFF"
DEFAULT_ACCENT = "#3CD3A4"
DEFAULT_FONT = "Raleway"


class Carousel(Base, TenantMixin, TimestampMixin):
    __tablename__ = "carousels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    platform: Mapped[str] = mapped_column(String(20), default="instagram", nullable=False)
    slides: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default=STATUS_DRAFT, nullable=False)
    handle: Mapped[str] = mapped_column(String(120), default="", nullable=False)  # @ do Instagram
    caption: Mapped[str] = mapped_column(Text, default="", nullable=False)
    hashtags: Mapped[str] = mapped_column(String(600), default="", nullable=False)

    # Template personalizável (cores + fonte + layout)
    template: Mapped[str] = mapped_column(String(24), default="moderno", nullable=False)
    primary_color: Mapped[str] = mapped_column(String(9), default=DEFAULT_PRIMARY, nullable=False)
    bg_color: Mapped[str] = mapped_column(String(9), default=DEFAULT_BG, nullable=False)
    text_color: Mapped[str] = mapped_column(String(9), default=DEFAULT_TEXT, nullable=False)
    accent_color: Mapped[str] = mapped_column(String(9), default=DEFAULT_ACCENT, nullable=False)
    font: Mapped[str] = mapped_column(String(40), default=DEFAULT_FONT, nullable=False)
