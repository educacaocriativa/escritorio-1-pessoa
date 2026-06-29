"""Schemas do módulo Agenda. Espelham packages/shared-types (AgendaEvent)."""
from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.modules.agenda.models import (
    ALL_KINDS,
    ALL_PRIORITIES,
    ALL_STATUSES,
    PRIORITY_NORMAL,
)


def _ensure_aware(v: datetime) -> datetime:
    """Datetime naive é assumido como UTC. Evita comparar instantes inconsistentes na
    detecção de conflito (campos do banco são timezone-aware)."""
    if v.tzinfo is None:
        return v.replace(tzinfo=UTC)
    return v


class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    kind: str
    starts_at: datetime
    ends_at: datetime
    all_day: bool = False
    priority: str = PRIORITY_NORMAL
    source: str = "manual"
    amount_cents: int | None = Field(default=None, ge=0)
    external_ref: str | None = None

    _aware = field_validator("starts_at", "ends_at")(_ensure_aware)

    @model_validator(mode="after")
    def _validate(self) -> EventCreate:
        if self.kind not in ALL_KINDS:
            raise ValueError(f"kind inválido: {self.kind}")
        if self.priority not in ALL_PRIORITIES:
            raise ValueError(f"priority inválida: {self.priority}")
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at deve ser posterior a starts_at (duração positiva)")
        return self


class EventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: str | None = None
    priority: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> EventUpdate:
        if self.status is not None and self.status not in ALL_STATUSES:
            raise ValueError(f"status inválido: {self.status}")
        if self.priority is not None and self.priority not in ALL_PRIORITIES:
            raise ValueError(f"priority inválida: {self.priority}")
        return self


class RescheduleRequest(BaseModel):
    starts_at: datetime
    ends_at: datetime

    _aware = field_validator("starts_at", "ends_at")(_ensure_aware)

    @model_validator(mode="after")
    def _validate(self) -> RescheduleRequest:
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at deve ser posterior a starts_at (duração positiva)")
        return self


class EventOut(BaseModel):
    id: str
    tenant_id: str
    title: str
    description: str
    kind: str
    status: str
    priority: str
    source: str
    starts_at: datetime
    ends_at: datetime
    all_day: bool
    amount_cents: int | None
    external_ref: str | None
    created_by_ai: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateEventResult(BaseModel):
    """Evento criado + conflitos detectados (a 'Guardiã da Agenda' avisa, não bloqueia)."""

    event: EventOut
    conflicts: list[EventOut]
