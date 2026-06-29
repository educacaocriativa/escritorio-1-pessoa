"""Modelos do CRM: PipelineStage (colunas do Kanban) e Client (cliente/lead).

O funil é dinâmico: cada tenant tem suas colunas ordenadas (Entrada → ... → Ganho/Perda).
Cada Client é um card que vive em um estágio. Tabelas de NEGÓCIO → RLS na migration.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

# Gênero (para segmentação demográfica citada na spec).
GENDER_VALUES = {"male", "female", "other", "unspecified"}
SOURCE_VALUES = {"manual", "landing", "ai", "import"}

# Colunas padrão criadas no primeiro acesso ao board de um tenant.
DEFAULT_STAGES = [
    {"name": "Entrada", "is_won": False, "is_lost": False},
    {"name": "Em contato", "is_won": False, "is_lost": False},
    {"name": "Proposta", "is_won": False, "is_lost": False},
    {"name": "Ganho", "is_won": True, "is_lost": False},
    {"name": "Perda", "is_won": False, "is_lost": True},
]


class PipelineStage(Base, TenantMixin, TimestampMixin):
    __tablename__ = "pipeline_stages"
    # Nome único por tenant — impede seed duplicado em corrida e colunas ambíguas.
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_stage_tenant_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_won: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_lost: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Client(Base, TenantMixin, TimestampMixin):
    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    document: Mapped[str | None] = mapped_column(String(18), nullable=True)  # CPF
    gender: Mapped[str] = mapped_column(String(12), default="unspecified", nullable=False)
    birthdate: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Tags livres para segmentação (ex.: "Tem Filhos", "Clicou no Preço").
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)

    # RESTRICT: não dá para excluir um estágio que ainda tem clientes (evita cards órfãos
    # sumindo do board). Coerente com o bloqueio em delete_stage.
    stage_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("pipeline_stages.id", ondelete="RESTRICT"), nullable=True, index=True
    )
