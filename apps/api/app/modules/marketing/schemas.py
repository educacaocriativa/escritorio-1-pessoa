"""Schemas do gerador de carrossel (estilo editorial)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.marketing.models import (
    DEFAULT_ACCENT,
    DEFAULT_BG,
    DEFAULT_FONT,
    DEFAULT_PRIMARY,
    DEFAULT_TEXT,
)


class Slide(BaseModel):
    kind: str = "editorial"  # cover | editorial | accent | cta
    heading: str = Field(default="", max_length=200)  # título (capa/cta) / texto principal
    body: str = Field(default="", max_length=600)
    secondary: str = Field(default="", max_length=400)  # texto complementar (editorial)
    highlight: str = Field(default="", max_length=80)  # palavra a destacar (acento)
    photo_url: str = Field(default="", max_length=1024)  # foto opcional (fundo/contida)
    photo_position: str = "mid"  # top | mid | base


class GenerateRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=500)
    slides: int = Field(default=7, ge=3, le=10)
    tone: str = Field(default="investigativo e direto", max_length=60)


class GenerateResult(BaseModel):
    slides: list[Slide]
    caption: str = ""
    hashtags: str = ""


class CarouselCreate(BaseModel):
    topic: str = Field(min_length=3, max_length=500)
    slides: list[Slide] = Field(default_factory=list)
    handle: str = Field(default="", max_length=120)
    caption: str = ""
    hashtags: str = Field(default="", max_length=600)
    template: str = "editorial"
    primary_color: str = Field(default=DEFAULT_PRIMARY, max_length=9)
    bg_color: str = Field(default=DEFAULT_BG, max_length=9)
    text_color: str = Field(default=DEFAULT_TEXT, max_length=9)
    accent_color: str = Field(default=DEFAULT_ACCENT, max_length=9)
    font: str = Field(default=DEFAULT_FONT, max_length=40)


class CarouselUpdate(BaseModel):
    topic: str | None = Field(default=None, min_length=3, max_length=500)
    slides: list[Slide] | None = None
    status: str | None = None
    handle: str | None = Field(default=None, max_length=120)
    caption: str | None = None
    hashtags: str | None = Field(default=None, max_length=600)
    template: str | None = Field(default=None, max_length=24)
    primary_color: str | None = Field(default=None, max_length=9)
    bg_color: str | None = Field(default=None, max_length=9)
    text_color: str | None = Field(default=None, max_length=9)
    accent_color: str | None = Field(default=None, max_length=9)
    font: str | None = Field(default=None, max_length=40)


class CarouselOut(BaseModel):
    id: str
    tenant_id: str
    topic: str
    platform: str
    slides: list[Slide]
    status: str
    handle: str
    caption: str
    hashtags: str
    template: str
    primary_color: str
    bg_color: str
    text_color: str
    accent_color: str
    font: str
    created_at: datetime


class TemplatePreset(BaseModel):
    key: str
    label: str
    primary_color: str
    bg_color: str
    text_color: str
    accent_color: str
    font: str
