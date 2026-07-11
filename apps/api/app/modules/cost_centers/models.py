"""Centro de custo — entidade de NEGÓCIO (RLS), 2ª dimensão de análise (Story 5.5).

`kind` é TEXTO LIVRE categorizado (sócio/área/unidade/outro são apenas SUGESTÕES oferecidas na UI):
ao contrário do `grupo_dre` do plano de contas (Story 5.1), que é um enum FIXO de produto, aqui o
usuário NÃO é travado a um vocabulário fechado — o AC1 cita "sócio/área/unidade" como EXEMPLOS de
uso, não como lista exaustiva. NÃO confundir os dois padrões (o backend não valida `kind` contra
`SUGGESTED_KINDS`).

Arquivar é lógico (seta `archived_at`, não deleta a linha) — preserva o histórico já vinculado,
mesmo padrão do plano de contas. `UniqueConstraint(tenant_id, name)`: nome único por tenant.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

# Tipos SUGERIDOS (vocabulário oferecido na UI). NÃO é enum fechado — o backend aceita qualquer
# texto curto e NÃO valida contra esta lista (contraste deliberado com `grupo_dre` da 5.1).
KIND_SOCIO = "socio"
KIND_AREA = "area"
KIND_UNIDADE = "unidade"
KIND_OUTRO = "outro"
SUGGESTED_KINDS: tuple[str, ...] = (KIND_SOCIO, KIND_AREA, KIND_UNIDADE, KIND_OUTRO)


class CostCenter(Base, TenantMixin, TimestampMixin):
    __tablename__ = "cost_centers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_cost_center_tenant_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Categorização livre (sócio/área/unidade/outro sugeridos). Default "outro".
    kind: Mapped[str] = mapped_column(String(16), default=KIND_OUTRO, nullable=False)
    # Arquivamento lógico: some da listagem padrão, mas a linha permanece (preserva o histórico
    # de lançamentos já vinculados a este centro de custo).
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
