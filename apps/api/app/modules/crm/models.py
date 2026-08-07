"""Modelos do CRM: PipelineStage (colunas do Kanban) e Client (cliente/lead).

O funil é dinâmico: cada tenant tem suas colunas ordenadas (Entrada → ... → Ganho/Perda).
Cada Client é um card que vive em um estágio. Tabelas de NEGÓCIO → RLS na migration.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

# Gênero (para segmentação demográfica citada na spec).
GENDER_VALUES = {"male", "female", "other", "unspecified"}
SOURCE_VALUES = {"manual", "landing", "ai", "import", "api", "whatsapp"}

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
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Client(Base, TenantMixin, TimestampMixin):
    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Forma COMPARÁVEL do telefone (ver `core/phone.normalize_br`). `phone` guarda o que a
    # pessoa digitou; esta guarda "5511999998888". Indexada porque é o caminho de busca do
    # `absorb_lead`. SEM unique: marido e mulher compartilham telefone, e uma constraint
    # quebraria a criação manual legítima de dois contatos com o mesmo número.
    phone_key: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
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

    # Desde quando este card está NESTA etapa. É a ordem da fila do Kanban: o mais antigo no
    # topo, quem entra vai para o fim, para que o dono atenda por ordem de chegada.
    #
    # Coluna, e não derivação de `client_events`, porque os três caminhos que escrevem
    # `stage_id` registram coisas diferentes — `move_client` grava `stage_move`, a reabertura
    # do `absorb_lead` grava `reopened`, e `archive_stage` remaneja em massa sem evento
    # nenhum. Não é valor derivado materializado (o caso que `last_interaction_map` recusa);
    # é fato primário que não tinha onde morar.
    #
    # Default do lado do PYTHON, sobrescrevendo o `server_default`: no Postgres `now()` é o
    # instante da TRANSAÇÃO, então dois carimbos no mesmo commit sairiam idênticos e o
    # desempate cairia no uuid. Mesma razão de `ClientEvent.created_at`.
    stage_entered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


# ── Linha do tempo do contato ──────────────────────────

# Vocabulário FECHADO. Cada valor vira um ícone e uma cor na tela; um valor novo sem
# tratamento no front apareceria sem identidade visual.
