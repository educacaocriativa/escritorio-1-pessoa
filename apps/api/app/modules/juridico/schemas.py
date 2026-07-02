"""Schemas do Assistente Jurídico."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SkillSummary(BaseModel):
    skill: str
    label: str
    category: str
    description: str
    output_type: str


class DocumentCreate(BaseModel):
    skill: str
    answers: dict = {}
    client_id: str | None = None
    # Texto já extraído de anexos (PDF/Word/imagem), concatenado pelo front via /juridico/extract.
    extracted_text: str = ""


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    skill: str
    category: str
    title: str
    client_id: str | None
    client_name: str | None = None
    content: str
    metadata_raw: str
    answers: dict
    input_tokens: int
    output_tokens: int
    status: str
    created_at: datetime


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    skill: str
    category: str
    title: str
    client_id: str | None
    client_name: str | None = None
    status: str
    created_at: datetime


class ExtractResult(BaseModel):
    filename: str
    chars: int
    text: str
