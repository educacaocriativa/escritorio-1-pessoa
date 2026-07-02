"""Construtor de Funil de Vendas — grafo visual (estilo React Flow) + motor de automação.

Funnel = um diagrama com nós (gatilhos/lógica/ações/comunicação/tráfego) e arestas (conexões).
Guardamos os nós e arestas como JSON no formato do React Flow. Tabela de NEGÓCIO (RLS).

FunnelRun = a JORNADA de UM contato dentro de um funil (estado por contato). O motor anda
pelo grafo executando as ações reais; nós de "esperar" pausam a jornada até `resume_at`, que o
agendador (tick) retoma. Tabela de NEGÓCIO (RLS).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

# Estados de uma jornada.
RUN_RUNNING = "running"
RUN_WAITING = "waiting"
RUN_DONE = "done"
RUN_FAILED = "failed"
RUN_CANCELLED = "cancelled"


class Funnel(Base, TenantMixin, TimestampMixin):
    __tablename__ = "funnels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    nodes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    edges: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


class FunnelRun(Base, TenantMixin, TimestampMixin):
    __tablename__ = "funnel_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    funnel_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    # O contato que percorre o funil (liga ao CRM). Pode ser nulo para jornadas sem contato.
    client_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default=RUN_RUNNING, nullable=False)
    # Próximo nó a processar (ou o nó seguinte ao "esperar", quando aguardando).
    current_node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Quando a jornada está "waiting", instante em que o agendador deve retomá-la.
    resume_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Log de execução: [{node_id, key, action, status, message, at}].
    steps: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    error: Mapped[str] = mapped_column(String(500), default="", nullable=False)
