"""Schemas do plano de contas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.modules.chart_of_accounts.models import ALL_GROUPS


class ChartAccountCreate(BaseModel):
    grupo_dre: str
    categoria: str = Field(min_length=1, max_length=80)

    @field_validator("grupo_dre")
    @classmethod
    def _grupo(cls, v: str) -> str:
        if v not in ALL_GROUPS:
            raise ValueError(f"grupo DRE inválido: {v}")
        return v

    @field_validator("categoria")
    @classmethod
    def _categoria(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("categoria não pode ser vazia")
        return v


class ChartAccountUpdate(BaseModel):
    categoria: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("categoria")
    @classmethod
    def _categoria(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("categoria não pode ser vazia")
        return v


class ChartAccountOut(BaseModel):
    id: str
    grupo_dre: str
    categoria: str
    archived_at: datetime | None
    created_at: datetime


class ChartGroupOut(BaseModel):
    """Um grupo DRE com suas categorias (nó da hierarquia grupo → categorias — AC3)."""

    grupo_dre: str
    categorias: list[ChartAccountOut]
