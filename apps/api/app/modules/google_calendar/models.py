"""Credencial Google por tenant (token de acesso à Calendar API do owner).

Uma linha por tenant (mesmo padrão 1:1 de TenantProfile). Tabela de NEGÓCIO → herda
TenantMixin (RLS aplicada na migration). O app OAuth em si (client_id/secret) é GLOBAL e vive
em config; aqui guardamos só o token da conta que CADA owner conectou.

IV3 / segurança: access_token e refresh_token NUNCA são expostos em schema de resposta nem em
log. Além da RLS, os tokens são CIFRADOS EM REPOUSO (Fernet) via o tipo `EncryptedToken`: o
banco guarda ciphertext, o código sempre vê texto plano (transparente). Endurecimento da dívida
técnica sinalizada na Story 4.1 — ver app/core/token_crypto.py.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.token_crypto import EncryptedToken
from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

DEFAULT_SCOPE = (
    "https://www.googleapis.com/auth/calendar.events"
    " https://www.googleapis.com/auth/userinfo.email"
)


class GoogleCredential(Base, TenantMixin, TimestampMixin):
    __tablename__ = "google_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    google_account_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    access_token: Mapped[str] = mapped_column(EncryptedToken, default="", nullable=False)
    refresh_token: Mapped[str] = mapped_column(EncryptedToken, default="", nullable=False)
    token_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scope: Mapped[str] = mapped_column(String(255), default=DEFAULT_SCOPE, nullable=False)
