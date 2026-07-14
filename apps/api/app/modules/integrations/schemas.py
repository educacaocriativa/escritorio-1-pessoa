"""Schemas do módulo de Integrações (chaves de captura de lead)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class IntegrationKeyCreate(BaseModel):
    label: str = Field(min_length=1, max_length=255)


class IntegrationKeyOut(BaseModel):
    id: str
    label: str
    key_prefix: str
    revoked_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class IntegrationKeyCreated(IntegrationKeyOut):
    """Retorno da criação: única vez em que a chave crua fica visível."""

    raw_key: str


class LeadCapture(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    # Campos livres do formulário externo (ex.: "ocasião", "nº de convidados") sem equivalente
    # direto no CRM — viram um bloco de texto anexado a `notes`, sem inventar colunas novas.
    fields: dict[str, str] | None = None
