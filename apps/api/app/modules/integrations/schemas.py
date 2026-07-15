"""Schemas do módulo de Integrações (chaves de captura de lead)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


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
    # Observação livre do formulário externo (ex.: "prefere data em dezembro").
    notes: str | None = Field(default=None, max_length=2000)
    # Campos livres do formulário externo (ex.: "ocasião", "nº de convidados") sem equivalente
    # direto no CRM — viram um bloco de texto anexado a `notes`, sem inventar colunas novas.
    fields: dict[str, str] | None = None

    @field_validator("email", mode="before")
    @classmethod
    def _blank_email_to_none(cls, v: object) -> object:
        # Formulário HTML externo com campo opcional vazio manda `""`, não omite a chave nem
        # manda `null` — sem isso o EmailStr rejeita string vazia com 422 e o lead se perde.
        if isinstance(v, str) and not v.strip():
            return None
        return v
