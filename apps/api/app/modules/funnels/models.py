"""Construtor de Funil de Vendas — grafo visual (estilo React Flow).

Funnel = um diagrama com nós (gatilhos/lógica/ações/comunicação/tráfego) e arestas (conexões).
Guardamos os nós e arestas como JSON no formato do React Flow. Tabela de NEGÓCIO (RLS).
"""
from __future__ import annotations

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid


class Funnel(Base, TenantMixin, TimestampMixin):
    __tablename__ = "funnels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    nodes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    edges: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
