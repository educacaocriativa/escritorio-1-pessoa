"""Schemas do Construtor de Contratos + Assinatura."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Clause(BaseModel):
    title: str = Field(default="", max_length=255)
    text: str = Field(min_length=1)


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    clauses: list[Clause] = Field(min_length=1)


class TemplateOut(BaseModel):
    id: str
    name: str
    clauses: list[Clause]
    created_at: datetime


class ContractCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    client_id: str | None = None
    quote_id: str | None = None
    clauses: list[Clause] = Field(min_length=1)
    # substituições aplicadas nas cláusulas: {"VALOR": "R$ 1.000"} troca [VALOR]
    variables: dict[str, str] = Field(default_factory=dict)


class ContractUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    client_id: str | None = None
    clauses: list[Clause] | None = None


class ContractOut(BaseModel):
    id: str
    tenant_id: str
    client_id: str | None
    client_name: str | None
    quote_id: str | None
    title: str
    clauses: list[Clause]
    status: str
    public_slug: str | None
    signer_name: str
    signer_document: str
    signed_at: datetime | None
    created_at: datetime


class ContractsSummary(BaseModel):
    draft_count: int
    sent_count: int
    signed_count: int


# ── Assinatura pública (cliente abre o link, sem login) ─────────────────────
class PublicContract(BaseModel):
    title: str
    company_name: str
    clauses: list[Clause]
    status: str
    signer_name: str
    signed_at: datetime | None


class SignRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    document: str = Field(min_length=3, max_length=32)  # CPF/CNPJ (KYC)
    accept: bool = True
