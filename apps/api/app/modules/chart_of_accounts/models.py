"""Plano de contas — entidade de NEGÓCIO (RLS).

Grupo DRE é um enum FIXO de produto (6 valores, não editável pelo tenant); `categoria` é livre
(nome), única por tenant dentro do grupo. Arquivar não deleta a linha (preserva histórico já
classificado — AC2). Segue o padrão de módulo de `Payable`/`Charge` (Tenant/Timestamp mixins).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

# Grupos DRE — enum FIXO de produto. Ordem canônica usada na hierarquia (receita → resultado).
GRUPO_RECEITA = "RECEITA"
GRUPO_CUSTO_DIRETO = "CUSTO_DIRETO"
GRUPO_DESPESA_FIXA = "DESPESA_FIXA"
GRUPO_TRIBUTOS = "TRIBUTOS"
GRUPO_FINANCEIRO = "FINANCEIRO"
GRUPO_INVESTIMENTO = "INVESTIMENTO"

# Ordem canônica (usada no endpoint hierárquico). ALL_GROUPS deriva daqui para não divergir.
GROUP_ORDER: tuple[str, ...] = (
    GRUPO_RECEITA,
    GRUPO_CUSTO_DIRETO,
    GRUPO_DESPESA_FIXA,
    GRUPO_TRIBUTOS,
    GRUPO_FINANCEIRO,
    GRUPO_INVESTIMENTO,
)
ALL_GROUPS: frozenset[str] = frozenset(GROUP_ORDER)


class ChartAccount(Base, TenantMixin, TimestampMixin):
    __tablename__ = "chart_accounts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "grupo_dre",
            "categoria",
            name="uq_chart_account_tenant_group_categoria",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    grupo_dre: Mapped[str] = mapped_column(String(20), nullable=False)
    categoria: Mapped[str] = mapped_column(String(80), nullable=False)
    # Arquivamento lógico: some da listagem padrão, mas a linha permanece (preserva histórico).
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
