"""Schemas do centro de custo (Story 5.5)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.modules.cost_centers.models import KIND_OUTRO


def _clean_kind(v: str | None) -> str | None:
    """Normaliza o `kind` (texto livre): trim; vazio → 'outro'. NÃO valida contra vocabulário
    fixo (centro de custo é dimensão livre — ver docstring do modelo)."""
    if v is None:
        return None
    v = v.strip()
    return v or KIND_OUTRO


class CostCenterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(default=KIND_OUTRO, max_length=16)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("nome não pode ser vazio")
        return v

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        return _clean_kind(v) or KIND_OUTRO


class CostCenterUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: str | None = Field(default=None, max_length=16)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("nome não pode ser vazio")
        return v

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str | None) -> str | None:
        return _clean_kind(v)


class CostCenterOut(BaseModel):
    id: str
    name: str
    kind: str
    archived_at: datetime | None
    created_at: datetime
