"""Schemas de Anexos (metadados — sem os bytes)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AttachmentOut(BaseModel):
    id: str
    owner_type: str
    owner_id: str
    label: str
    filename: str
    content_type: str
    size: int
    created_at: datetime


class PublicImageOut(BaseModel):
    """Retorno do upload de imagem pública. ``url`` é o caminho da rota de leitura no backend
    (``/public-images/{id}``); o frontend prefixa o proxy ``/api`` para obter a URL renderável."""

    id: str
    url: str
