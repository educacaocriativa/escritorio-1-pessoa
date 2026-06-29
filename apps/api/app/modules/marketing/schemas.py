"""Schemas do gerador de carrossel."""
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
    heading: str = Field(default="", max_length=120)
    body: str = Field(default="", max_length=500)


class GenerateRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=500)
    slides: int = Field(default=6, ge=3, le=10)
    tone: str = Field(default="profissional e direto", max_length=60)


class CarouselCreate(BaseModel):
    topic: str = Field(min_length=3, max_length=500)
    slides: list[Slide] = Field(default_factory=list)
    template: str = "moderno"
    primary_color: str = Field(default=DEFAULT_PRIMARY, max_length=9)
    bg_color: str = Field(default=DEFAULT_BG, max_length=9)
    text_color: str = Field(default=DEFAULT_TEXT, max_length=9)
    accent_color: str = Field(default=DEFAULT_ACCENT, max_length=9)
    font: str = Field(default=DEFAULT_FONT, max_length=40)


class CarouselUpdate(BaseModel):
    topic: str | None = Field(default=None, min_length=3, max_length=500)
    slides: list[Slide] | None = None
    status: str | None = None
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


class GenerateResult(BaseModel):
    slides: list[Slide]
