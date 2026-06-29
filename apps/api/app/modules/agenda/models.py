"""Modelo do evento de Agenda — o núcleo do e1p.

Tudo no sistema converge para a Agenda: atendimentos, reuniões, prazos jurídicos, audiências,
cobranças a receber/pagar e lembretes são todos `AgendaEvent` com `kind` diferente. Outros
módulos injetam eventos aqui (campo `source` indica a origem).

Tabela de NEGÓCIO → herda TenantMixin (RLS aplicada na migration).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

# Tipos de evento. Os que OCUPAM tempo geram conflito; os demais são marcadores.
KIND_ATENDIMENTO = "atendimento"
KIND_REUNIAO = "reuniao"
KIND_AUDIENCIA = "audiencia"
KIND_BLOQUEIO = "bloqueio"
KIND_PRAZO = "prazo"
KIND_COBRANCA_RECEBER = "cobranca_receber"
KIND_COBRANCA_PAGAR = "cobranca_pagar"
KIND_LEMBRETE = "lembrete"

ALL_KINDS = {
    KIND_ATENDIMENTO, KIND_REUNIAO, KIND_AUDIENCIA, KIND_BLOQUEIO,
    KIND_PRAZO, KIND_COBRANCA_RECEBER, KIND_COBRANCA_PAGAR, KIND_LEMBRETE,
}
# Eventos que ocupam um intervalo de tempo (entram na checagem de conflito de agenda).
OCCUPYING_KINDS = {KIND_ATENDIMENTO, KIND_REUNIAO, KIND_AUDIENCIA, KIND_BLOQUEIO}

STATUS_SCHEDULED = "scheduled"
STATUS_CONFIRMED = "confirmed"
STATUS_CANCELLED = "cancelled"
STATUS_DONE = "done"
ALL_STATUSES = {STATUS_SCHEDULED, STATUS_CONFIRMED, STATUS_CANCELLED, STATUS_DONE}

PRIORITY_NORMAL = "normal"
PRIORITY_HIGH = "high"
PRIORITY_CRITICAL = "critical"  # ex.: prazo processual fatal (tarja vermelha)
ALL_PRIORITIES = {PRIORITY_NORMAL, PRIORITY_HIGH, PRIORITY_CRITICAL}


class AgendaEvent(Base, TenantMixin, TimestampMixin):
    __tablename__ = "agenda_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_SCHEDULED, nullable=False)
    priority: Mapped[str] = mapped_column(String(12), default=PRIORITY_NORMAL, nullable=False)
    # Origem do evento: "manual", "ai", "financeiro", "juridico", "crm", "contratos"...
    source: Mapped[str] = mapped_column(String(24), default="manual", nullable=False)

    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Dinheiro SEMPRE em centavos inteiros (evita erro de float). Opcional (cobranças).
    amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Referência à entidade de origem (id do processo, fatura, contrato...).
    external_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_by_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
