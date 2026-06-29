"""Schemas do CRM. Espelham packages/shared-types."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.modules.crm.models import GENDER_VALUES, SOURCE_VALUES

# ── Estágios (colunas do Kanban) ───────────────────────


class StageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    position: int | None = None
    is_won: bool = False
    is_lost: bool = False

    @model_validator(mode="after")
    def _validate(self) -> StageCreate:
        if self.is_won and self.is_lost:
            raise ValueError("um estágio não pode ser 'ganho' e 'perda' ao mesmo tempo")
        return self


class StageUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    position: int | None = None


class StageOut(BaseModel):
    id: str
    name: str
    position: int
    is_won: bool
    is_lost: bool

    model_config = {"from_attributes": True}


# ── Clientes (cards) ───────────────────────────────────


class ClientBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    document: str | None = Field(default=None, max_length=18)
    gender: str = "unspecified"
    birthdate: date | None = None
    notes: str = ""
    tags: list[str] = Field(default_factory=list)
    source: str = "manual"

    @field_validator("gender")
    @classmethod
    def _gender(cls, v: str) -> str:
        if v not in GENDER_VALUES:
            raise ValueError(f"gender inválido: {v}")
        return v

    @field_validator("source")
    @classmethod
    def _source(cls, v: str) -> str:
        if v not in SOURCE_VALUES:
            raise ValueError(f"source inválido: {v}")
        return v

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        # normaliza: sem vazias, sem duplicadas, trim; limita quantidade e tamanho.
        seen: list[str] = []
        for t in v:
            t = t.strip()
            if t and t not in seen:
                if len(t) > 40:
                    raise ValueError("tag muito longa (máx. 40 caracteres)")
                seen.append(t)
        if len(seen) > 50:
            raise ValueError("máximo de 50 tags por cliente")
        return seen

    @field_validator("birthdate")
    @classmethod
    def _birthdate(cls, v: date | None) -> date | None:
        if v is not None and v > date.today():
            raise ValueError("birthdate não pode estar no futuro")
        return v


class ClientCreate(ClientBase):
    stage_id: str | None = None


class ClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = None
    document: str | None = None
    gender: str | None = None
    birthdate: date | None = None
    notes: str | None = None
    tags: list[str] | None = None

    @field_validator("gender")
    @classmethod
    def _gender(cls, v: str | None) -> str | None:
        if v is not None and v not in GENDER_VALUES:
            raise ValueError(f"gender inválido: {v}")
        return v


class MoveClientRequest(BaseModel):
    stage_id: str


class ClientOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    email: str | None
    phone: str | None
    document: str | None
    gender: str
    birthdate: date | None
    notes: str
    tags: list[str]
    source: str
    stage_id: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Board (Kanban montado) ─────────────────────────────


class BoardColumn(BaseModel):
    stage: StageOut
    clients: list[ClientOut]


class Board(BaseModel):
    columns: list[BoardColumn]
