"""Schemas de notificações."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: str
    channel: str
    recipient: str
    client_id: str | None
    message: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
