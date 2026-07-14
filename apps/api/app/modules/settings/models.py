"""Configurações + Brand Kit do tenant.

TenantProfile: uma linha por tenant (RLS) com o perfil da empresa e o Brand Kit
(logo, cores, fonte) reaproveitado em propostas, contratos e carrosséis.
"""
from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

DEFAULT_PRIMARY = "#5D44F8"
DEFAULT_SECONDARY = "#3DD68C"
DEFAULT_ACCENT = "#3DD68C"
DEFAULT_TEXT = "#1F2937"
DEFAULT_BG = "#FFFFFF"
DEFAULT_FONT = "Inter"
DEFAULT_TIMEZONE = "America/Sao_Paulo"


class TenantProfile(Base, TenantMixin, TimestampMixin):
    __tablename__ = "tenant_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Perfil da empresa
    display_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    document: Mapped[str] = mapped_column(String(18), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    address: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    website: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    about: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Brand Kit
    logo_url: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    primary_color: Mapped[str] = mapped_column(String(9), default=DEFAULT_PRIMARY, nullable=False)
    secondary_color: Mapped[str] = mapped_column(
        String(9), default=DEFAULT_SECONDARY, nullable=False
    )
    accent_color: Mapped[str] = mapped_column(String(9), default=DEFAULT_ACCENT, nullable=False)
    text_color: Mapped[str] = mapped_column(String(9), default=DEFAULT_TEXT, nullable=False)
    bg_color: Mapped[str] = mapped_column(String(9), default=DEFAULT_BG, nullable=False)
    font: Mapped[str] = mapped_column(String(40), default=DEFAULT_FONT, nullable=False)
    # Fuso horário do tenant (IANA). Ancora janelas do dia / eventos all-day (Agenda/Cockpit).
    timezone: Mapped[str] = mapped_column(
        String(64), default=DEFAULT_TIMEZONE, nullable=False
    )
    # Funil de Vendas em que todo lead novo (source=landing/api) é inscrito automaticamente.
    # None = sem auto-enroll (comportamento padrão até o dono configurar). Sem FK dura pra
    # `funnels.id` (mesmo padrão do projeto): funil apagado só faz o auto-enroll no-opar.
    default_entry_funnel_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
