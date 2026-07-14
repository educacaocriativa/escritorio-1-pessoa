"""Integrações: chaves de API para captura de lead de sites externos.

IntegrationKey = chave gerenciável (RLS) — o dono cria/revoga em `/integrations/leads/keys`.
PublicIntegrationKey = snapshot GLOBAL (sem RLS), chaveado pelo hash da chave — permite à rota
pública (`POST /public/leads/{key}`, sem login) resolver o tenant dono ANTES de qualquer
autenticação, mesmo padrão de `pages.PublishedPage`/`quotes.PublishedProposal`. Nunca guardamos
a chave em texto puro — só o hash (sha256) e um prefixo curto para identificação na lista.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid


class IntegrationKey(Base, TenantMixin, TimestampMixin):
    __tablename__ = "integration_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PublicIntegrationKey(Base, TimestampMixin):
    """Snapshot público (GLOBAL, sem RLS) da chave ativa — lookup pré-auth pelo hash."""

    __tablename__ = "public_integration_keys"

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
