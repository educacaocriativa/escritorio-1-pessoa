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
