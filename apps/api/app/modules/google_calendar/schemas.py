"""Schemas da integração Google. Espelham packages/shared-types (GoogleCalendarStatus).

IV3: NENHUM schema aqui expõe access_token/refresh_token — só status e o e-mail conectado.
"""
from __future__ import annotations

from pydantic import BaseModel


class GoogleStatusOut(BaseModel):
    """Estado da integração para o frontend decidir a UI (botões conectar/desconectar)."""

    # True = app OAuth configurado na plataforma (mostra/esconde o botão "Conectar").
    configured: bool
    # True = este tenant já conectou uma conta Google.
    connected: bool
    # E-mail da conta conectada (None se não conectado). Único dado da credencial exposto.
    email: str | None = None


class GoogleConnectOut(BaseModel):
    """URL de autorização do Google para o frontend redirecionar o usuário."""

    url: str
