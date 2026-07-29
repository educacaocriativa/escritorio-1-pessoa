"""Schemas do token de dispositivo."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DeviceTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class DeviceTokenOut(BaseModel):
    """Listagem — NUNCA carrega o token cru."""

    id: str
    name: str
    created_at: datetime
    last_used_at: datetime | None


class DeviceTokenCreated(BaseModel):
    """Resposta da criação — única vez em que o token cru sai do servidor."""

    id: str
    name: str
    token: str
