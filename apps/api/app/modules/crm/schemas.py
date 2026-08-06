"""Schemas do CRM. Espelham packages/shared-types."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.core.validators import validate_document
from app.modules.crm.models import GENDER_VALUES, SOURCE_VALUES

# ── Estágios (colunas do Kanban) ───────────────────────


class StageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    position: int | None = None
    after_stage_id: str | None = None
    is_won: bool = False
    is_lost: bool = False

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("nome não pode ser vazio")
        return v

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
    is_archived: bool = False

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

    @field_validator("document")
    @classmethod
    def _document(cls, v: str | None) -> str | None:
        # CPF/CNPJ do cliente é OPCIONAL: só valida (e normaliza) quando informado.
        if v is None or not v.strip():
            return None
        return validate_document(v)

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

    @field_validator("document")
    @classmethod
    def _document(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        return validate_document(v)

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
    # Desde quando o card está nesta etapa — a ordem da fila do Kanban. Fica em `ClientOut`
    # (e não em `BoardClient`, como `last_interaction_at`) porque é coluna: sempre conhecida,
    # nunca "não calculei". Não há o `null` ambíguo que justificou separar o outro campo.
    stage_entered_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Board (Kanban montado) ─────────────────────────────


class BoardClient(ClientOut):
    """`ClientOut` + a data da última interação.

    Campo separado do `ClientOut` de propósito: só o board calcula isso (via duas consultas
    agrupadas). Se `last_interaction_at` vivesse em `ClientOut`, todo endpoint que devolve
    cliente passaria a afirmar `null` — e `null` significaria tanto "sem interação" quanto
    "não calculei", que são coisas diferentes.
    """

    last_interaction_at: datetime | None = None


class BoardColumn(BaseModel):
    stage: StageOut
    clients: list[BoardClient]


class Board(BaseModel):
    columns: list[BoardColumn]


# ── Linha do tempo do contato ──────────────────────────


class ClientTimelineEntry(BaseModel):
    id: str
    kind: str
    title: str
    body: str
    actor: str
    is_ai: bool
    # `at`, e não `created_at`: para a cobrança paga o instante do fato é o `paid_at`. Um
    # nome só, um significado só, para as duas fontes poderem ser ordenadas juntas.
    at: datetime


class ClientTimelineOut(BaseModel):
    entries: list[ClientTimelineEntry]
    # `True` quando alguma fonte bateu no teto de 100. A tela avisa em vez de fingir que
    # aquilo é o histórico inteiro.
    truncated: bool


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=140)
    body: str = Field(default="", max_length=5000)

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("a nota precisa de um título")
        return v
