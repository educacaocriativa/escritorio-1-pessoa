"""Modelo do evento de Agenda — o núcleo do e1p.

Tudo no sistema converge para a Agenda: atendimentos, reuniões, prazos jurídicos, audiências,
cobranças a receber/pagar e lembretes são todos `AgendaEvent` com `kind` diferente. Outros
módulos injetam eventos aqui (campo `source` indica a origem).

Tabela de NEGÓCIO → herda TenantMixin (RLS aplicada na migration).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
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
# Evento espelhado a partir do Google Calendar (sync Google → e1p) — não tem tipo de negócio do
# e1p (não é reunião com cliente nem cobrança); ocupa horário de verdade na agenda do dono.
KIND_GOOGLE = "google"

ALL_KINDS = {
    KIND_ATENDIMENTO, KIND_REUNIAO, KIND_AUDIENCIA, KIND_BLOQUEIO,
    KIND_PRAZO, KIND_COBRANCA_RECEBER, KIND_COBRANCA_PAGAR, KIND_LEMBRETE, KIND_GOOGLE,
}
# Eventos que ocupam um intervalo de tempo (entram na checagem de conflito de agenda).
OCCUPYING_KINDS = {KIND_ATENDIMENTO, KIND_REUNIAO, KIND_AUDIENCIA, KIND_BLOQUEIO, KIND_GOOGLE}

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

    # Detalhes estilo Google Agenda
    location: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    meeting_url: Mapped[str | None] = mapped_column(String(512), nullable=True)  # link Meet/Zoom
    guests: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)  # e-mails
    # Id do evento espelhado no Google Calendar (quando o Meet foi gerado via OAuth Google, ou
    # quando o evento foi puxado de lá pelo sync — google_calendar/sync.py). Usado para
    # sincronizar reschedule/cancel de volta pro Google (ver agenda/service.py +
    # google_calendar/service.py::patch_meet_event/delete_meet_event).
    #
    # 1024, não 128: o próprio Google Calendar gera ids de ~26 chars, mas eventos IMPORTADOS de
    # calendários externos (Outlook/Exchange via interop do Workspace) chegam com ids de até
    # ~180+ chars — medido ao vivo em produção (2026-08-27), 3 ocorrências reais causando
    # `StringDataRightTruncation` e derrubando o lote de sync inteiro daquele tenant. 1024 é o
    # máximo documentado pela Google para o campo `id` do evento.
    google_event_id: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # De QUAL conta Google veio o `google_event_id` acima (migration 0086). Carimbado nos dois
    # pontos de escrita do id: `agenda/service.py::create_event` (a credencial que criou o
    # espelho lá) e `google_calendar/sync.py::_apply_item` (a credencial que puxou o evento).
    #
    # NULL tem SIGNIFICADO: procedência DESCONHECIDA — ou a linha é legada (gravada antes da
    # 0086, que não fez backfill de propósito), ou o `userinfo` do Google falhou e nunca
    # soubemos o e-mail. Em ambos os casos a limpeza de reconexão
    # (`google_calendar/service.py::_invalidar_vinculos_de_outra_conta`) NÃO toca a linha.
    google_account_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Dinheiro SEMPRE em centavos inteiros (evita erro de float). Opcional (cobranças).
    amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Referência à entidade de origem (id do processo, fatura, contrato...).
    external_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # De QUEM é este compromisso. Nullable é o caso normal: bloqueio de horário, prazo
    # interno e conta a pagar não têm cliente. Sem FK e `String(36)`, como
    # `whatsapp_chats.client_id` — a Agenda não deve ganhar dependência dura da tabela do CRM.
    #
    # Não confundir com `external_ref`: aquele é ponteiro POLIMÓRFICO, lido conforme o `kind`
    # (id de cobrança, de conta a pagar...). Este é sempre um `clients.id`.
    client_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    created_by_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
