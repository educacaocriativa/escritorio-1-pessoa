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


# ── Linha do tempo do contato ──────────────────────────

# Vocabulário FECHADO. Cada valor vira um ícone e uma cor na tela; um valor novo sem
# tratamento no front apareceria sem identidade visual.
KIND_LEAD_CREATED = "lead_created"   # o contato nasceu
KIND_LEAD_RETURN = "lead_return"     # contato conhecido voltou pelo formulário/API
KIND_STAGE_MOVE = "stage_move"       # card mudou de coluna (inclusive drag-and-drop)
KIND_REOPENED = "reopened"           # retorno reabriu card que estava em coluna terminal
KIND_NOTE = "note"                   # decisão escrita pelo dono
KIND_FUNNEL = "funnel"               # contato inscrito numa jornada do funil

EVENT_KINDS = (
    KIND_LEAD_CREATED, KIND_LEAD_RETURN, KIND_STAGE_MOVE,
    KIND_REOPENED, KIND_NOTE, KIND_FUNNEL,
)


class ClientEvent(Base, TenantMixin, TimestampMixin):
    """Um fato NARRATIVO na história de um contato.

    O que mora aqui: como chegou, quando voltou e com que texto, para onde foi no Kanban,
    o que foi decidido.

    O que NÃO mora aqui: dinheiro. Orçamento, cobrança e pagamento continuam vivendo só em
    `quotes`/`charges` e são lidos de lá (ver `crm/timeline.py`). Copiar `amount_cents` para
    cá criaria uma segunda versão da verdade sobre dinheiro — a forma exata do bug que a
    Onda 0 do Epic 8 gastou uma onda inteira desfazendo.

    `title` e `body` são TEXTO CONGELADO, não referências: um movimento gravado hoje diz
    "Movido de Em contato → Proposta" como texto, e continua dizendo isso mesmo depois de a
    coluna ser renomeada ou arquivada. É o princípio do `raw_description` de
    `bank_transactions` — o registro é evidência, e evidência não se reescreve sozinha.
    """

    __tablename__ = "client_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # CASCADE: a história de um contato não sobrevive ao contato. Diferente do RESTRICT de
    # `stage_id`, que existe para impedir card órfão sumindo do board.
    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(140), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    # Regra de Ouro nº 3: toda ação da IA deixa rastro identificável.
    is_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # `created_at` com default do lado do PYTHON, sobrescrevendo o `server_default=func.now()`
    # do TimestampMixin. No Postgres, `now()` é o timestamp da TRANSAÇÃO: dois eventos
    # gravados no MESMO commit — o que `absorb_lead` faz com `lead_return` + `reopened` —
    # sairiam com instante idêntico, e o desempate cairia no `id`, que é uuid aleatório. A
    # timeline mostraria "Reaberto em Entrada" acima de "Voltou pelo site", invertendo a
    # causalidade na tela. Com default em Python cada linha ganha seu próprio microssegundo.
    # O `server_default` fica para qualquer INSERT que não passe pelo ORM.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
