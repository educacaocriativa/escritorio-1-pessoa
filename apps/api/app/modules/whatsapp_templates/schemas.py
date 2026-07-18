"""Schemas do módulo de Templates de WhatsApp (Meta Cloud API)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TemplateCreate(BaseModel):
    # ex: "boas_vindas_lead" — a Meta só aceita minúsculas/números/underscore.
    name: str = Field(pattern=r"^[a-z0-9_]+$")
    language: str = "pt_BR"
    category: Literal["MARKETING", "UTILITY", "AUTHENTICATION"]
    # com {{1}}, {{2}}, ... (variáveis posicionais contíguas a partir de 1)
    body_text: str
    variable_examples: list[str] = []


class TemplateOut(BaseModel):
    id: str
    name: str
    language: str
    category_requested: str
    category_approved: str | None
    status: str
    rejected_reason: str | None
    meta_template_id: str | None
    body_text: str
    variable_count: int
    variable_examples: list[str]
    created_at: datetime
    updated_at: datetime
