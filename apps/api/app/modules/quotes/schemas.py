"""Schemas da Central de Orçamentos (construtor de proposta + visão pública)."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.modules.quotes.models import (
    DEFAULT_ACCENT,
    DEFAULT_BG,
    DEFAULT_PRIMARY,
    DEFAULT_TEXT,
)


class QuoteItem(BaseModel):
    description: str = Field(min_length=1, max_length=255)  # "Título exibido"
    subtitle: str = Field(default="", max_length=255)
    quantity: int = Field(gt=0)
    unit_price_cents: int = Field(ge=0)


class GalleryImage(BaseModel):
    url: str = Field(min_length=1, max_length=1024)
    caption: str = Field(default="", max_length=255)


class ScheduleStage(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    when: str = Field(default="", max_length=120)  # data ou texto livre ("Semana 1")
    description: str = Field(default="", max_length=500)


class _Builder(BaseModel):
    """Campos compartilhados pelas abas do construtor."""

    client_name: str = Field(default="", max_length=255)
    client_whatsapp: str = Field(default="", max_length=32)
    payment_terms: str = ""
    link_password: str | None = Field(default=None, max_length=128)
    show_gallery: bool = False
    gallery: list[GalleryImage] = Field(default_factory=list)
    show_schedule: bool = False
    schedule: list[ScheduleStage] = Field(default_factory=list)
    show_contract: bool = False
    contract_text: str = ""
    logo_url: str = Field(default="", max_length=512)
    primary_color: str = Field(default=DEFAULT_PRIMARY, max_length=9)
    bg_color: str = Field(default=DEFAULT_BG, max_length=9)
    text_color: str = Field(default=DEFAULT_TEXT, max_length=9)
    accent_color: str = Field(default=DEFAULT_ACCENT, max_length=9)


class QuoteCreate(_Builder):
    client_id: str | None = None
    title: str = Field(min_length=1, max_length=255)
    items: list[QuoteItem] = Field(min_length=1)
    discount_cents: int = Field(default=0, ge=0)
    valid_until: date | None = None
    notes: str = ""


class QuoteUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    client_id: str | None = None
    items: list[QuoteItem] | None = None
    discount_cents: int | None = Field(default=None, ge=0)
    valid_until: date | None = None
    notes: str | None = None
    client_name: str | None = Field(default=None, max_length=255)
    client_whatsapp: str | None = Field(default=None, max_length=32)
    payment_terms: str | None = None
    link_password: str | None = Field(default=None, max_length=128)  # "" remove a senha
    show_gallery: bool | None = None
    gallery: list[GalleryImage] | None = None
    show_schedule: bool | None = None
    schedule: list[ScheduleStage] | None = None
    show_contract: bool | None = None
    contract_text: str | None = None
    logo_url: str | None = Field(default=None, max_length=512)
    primary_color: str | None = Field(default=None, max_length=9)
    bg_color: str | None = Field(default=None, max_length=9)
    text_color: str | None = Field(default=None, max_length=9)
    accent_color: str | None = Field(default=None, max_length=9)


class QuoteOut(BaseModel):
    id: str
    tenant_id: str
    client_id: str | None
    client_name: str
    client_whatsapp: str
    title: str
    items: list[QuoteItem]
    discount_cents: int
    subtotal_cents: int
    total_cents: int
    status: str
    valid_until: date | None
    notes: str
    payment_terms: str
    has_password: bool
    show_gallery: bool
    gallery: list[GalleryImage]
    show_schedule: bool
    schedule: list[ScheduleStage]
    show_contract: bool
    contract_text: str
    logo_url: str
    primary_color: str
    bg_color: str
    text_color: str
    accent_color: str
    public_slug: str | None
    charge_id: str | None
    created_at: datetime


class QuotesSummary(BaseModel):
    draft_count: int
    sent_cents: int
    approved_cents: int
    approved_count: int


class ScopeRequest(BaseModel):
    brief: str = Field(min_length=2, max_length=500)


class ScopeResult(BaseModel):
    description: str


# ── Visão pública (cliente abre o link, sem login) ──────────────────────────
class PublicProposal(BaseModel):
    title: str
    client_name: str
    items: list[QuoteItem]
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    payment_terms: str
    show_gallery: bool
    gallery: list[GalleryImage]
    show_schedule: bool
    schedule: list[ScheduleStage]
    show_contract: bool
    contract_text: str
    logo_url: str
    primary_color: str
    bg_color: str
    text_color: str
    accent_color: str
    status: str
    valid_until: date | None


class PublicAccept(BaseModel):
    password: str | None = None
