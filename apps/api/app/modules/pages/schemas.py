"""Schemas do construtor de páginas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class PageCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    model: str = "conteudo"
    blocks: list[dict] | None = None  # se None, usa o template do modelo


class PageUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    blocks: list[dict] | None = None
    primary_color: str | None = Field(default=None, max_length=9)
    bg_color: str | None = Field(default=None, max_length=9)
    text_color: str | None = Field(default=None, max_length=9)
    accent_color: str | None = Field(default=None, max_length=9)
    font: str | None = Field(default=None, max_length=40)
    logo_url: str | None = Field(default=None, max_length=1024)


class PageOut(BaseModel):
    id: str
    tenant_id: str
    title: str
    model: str
    blocks: list[dict]
    status: str
    public_slug: str | None
    primary_color: str
    bg_color: str
    text_color: str
    accent_color: str
    font: str
    logo_url: str
    created_at: datetime


class PageSummary(BaseModel):
    id: str
    title: str
    model: str
    status: str
    public_slug: str | None
    created_at: datetime


class PublicPage(BaseModel):
    title: str
    blocks: list[dict]
    primary_color: str
    bg_color: str
    text_color: str
    accent_color: str
    font: str
    logo_url: str


class LeadSubmit(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str = Field(default="", max_length=32)
