"""Regras da Agenda: CRUD de eventos + detecção de conflitos de horário.

A sessão recebida já vem isolada por tenant (RLS) — não filtramos tenant manualmente nas
queries (Regra de Ouro nº 1). O tenant_id só é usado para CARIMBAR novas linhas.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core import audit, facts
from app.core.facts import AGENDA_EVENTO_CANCELADO, AGENDA_EVENTO_REMARCADO
from app.modules.agenda.models import (
    KIND_ATENDIMENTO,
    KIND_AUDIENCIA,
    KIND_BLOQUEIO,
    KIND_REUNIAO,
    OCCUPYING_KINDS,
    STATUS_CANCELLED,
    STATUS_DONE,
    AgendaEvent,
)
from app.modules.agenda.schemas import EventCreate, EventUpdate

# Estados terminais: não podem ser cancelados de novo nem remarcados.
TERMINAL_STATUSES = {STATUS_CANCELLED, STATUS_DONE}
# Tipos onde "reunião" faz sentido → candidatos a gerar Meet automático (Story 4.1).
MEET_KINDS = {KIND_REUNIAO, KIND_ATENDIMENTO, KIND_AUDIENCIA}
# Tipos espelhados no Google (create/reschedule/cancel), com ou sem Meet — mesmo conjunto de
# `google_calendar/service.py::PUSHED_KINDS`, mantido local de propósito (o módulo-núcleo Agenda
# não tem import real da integração opcional, só o lazy dentro da função abaixo).
PUSHED_KINDS = MEET_KINDS | {KIND_BLOQUEIO}
DEFAULT_LIST_LIMIT = 200
MAX_LIST_LIMIT = 500


class AgendaError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def find_conflicts(
    db: Session,
    starts_at: datetime,
    ends_at: datetime,
    *,
    exclude_id: str | None = None,
) -> list[AgendaEvent]:
    """Eventos que OCUPAM tempo e se sobrepõem ao intervalo [starts_at, ends_at).

    Sobreposição: a.start < b.end AND b.start < a.end. Eventos cancelados são ignorados.
    """
    stmt = select(AgendaEvent).where(
        and_(
            AgendaEvent.kind.in_(OCCUPYING_KINDS),
            AgendaEvent.status != STATUS_CANCELLED,
            AgendaEvent.starts_at < ends_at,
            starts_at < AgendaEvent.ends_at,
        )
    )
    if exclude_id is not None:
        stmt = stmt.where(AgendaEvent.id != exclude_id)
    return list(db.scalars(stmt).all())


def create_event(
    db: Session, *, tenant_id: str, actor: str, by_ai: bool, data: EventCreate
) -> tuple[AgendaEvent, list[AgendaEvent]]:
    starts_at = data.starts_at
    ends_at = data.ends_at

    if data.all_day:
        # Ancora o evento de dia inteiro na meia-noite REAL do fuso do tenant (convertida p/ UTC),
        # em vez da meia-noite UTC crua. Import lazy de settings.get_profile p/ não acoplar o
        # módulo-núcleo Agenda ao módulo settings (mesmo padrão de quotes→contracts no CLAUDE.md).
        from app.core.tz import day_window_utc
        from app.modules.settings.service import tenant_timezone

        # `tenant_timezone(db)`, e não `get_profile(...).timezone`: o fuso mora em `tenants` desde
        # a 0073, e a coluna do perfil ficou congelada. Também é melhor por si — este caminho não
        # precisava CRIAR perfil, que é o que `get_profile` faz.
        starts_at, ends_at = day_window_utc(data.starts_at.date(), tenant_timezone(db))

    conflicts: list[AgendaEvent] = []
    if data.kind in OCCUPYING_KINDS:
        conflicts = find_conflicts(db, starts_at, ends_at)

    event = AgendaEvent(
        tenant_id=tenant_id,
        title=data.title,
        description=data.description,
        kind=data.kind,
        priority=data.priority,
        source=data.source,
        starts_at=starts_at,
        ends_at=ends_at,
        all_day=data.all_day,
        location=data.location,
        meeting_url=data.meeting_url,
        guests=data.guests,
        amount_cents=data.amount_cents,
        external_ref=data.external_ref,
        client_id=data.client_id,
        created_by_ai=by_ai,
    )
    # Geração automática de Meet (Story 4.1): só quando é um evento de reunião, o usuário NÃO
    # informou um link manual (Zoom/etc. tem prioridade) e o tenant conectou o Google. Import
    # lazy do módulo de integração para não acoplar a Agenda-núcleo a uma extensão opcional
    # (mesmo padrão de quotes → contracts). Falha do Google não derruba a criação (IV1/IV2):
    # create_meet_event captura a exceção e retorna None.
    if event.kind in PUSHED_KINDS and not data.meeting_url:
        from app.modules.google_calendar import service as gcal

        result = gcal.create_meet_event(db, tenant_id=tenant_id, event=event)
        if result is not None:
            meeting_url, google_event_id, google_account_email = result
            if meeting_url:
                event.meeting_url = meeting_url
            event.google_event_id = google_event_id
            # De QUAL conta Google é este id (migration 0086). Vem junto do retorno, e não de um
            # `get_credential` novo, porque é a credencial que REALMENTE escreveu o evento lá.
            # Sem este carimbo, reconectar com outra conta deixaria o id apontando para um
            # calendário alheio — ver `google_calendar/service.py::upsert_credential`.
            event.google_account_email = google_account_email
    db.add(event)
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="agenda.event.create",
        target=event.id, is_ai=by_ai,
    )
    db.commit()
    db.refresh(event)
    return event, conflicts


def list_events(
    db: Session,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    kinds: list[str] | None = None,
    client_id: str | None = None,
    exclude_cancelled: bool = False,
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
) -> list[AgendaEvent]:
    # Módulo-núcleo: o volume cresce (cobranças/prazos injetam eventos). Sempre paginar.
    limit = max(1, min(limit, MAX_LIST_LIMIT))
    offset = max(0, offset)
    stmt = select(AgendaEvent)
    if start is not None:
        stmt = stmt.where(AgendaEvent.ends_at >= start)
    if end is not None:
        stmt = stmt.where(AgendaEvent.starts_at <= end)
    if kinds:
        stmt = stmt.where(AgendaEvent.kind.in_(kinds))
    if client_id is not None:
        # Filtro da ficha 360°: só os compromissos DESTE contato. Evento sem client_id (bloqueio,
        # prazo interno, conta a pagar) nunca casa — a coluna é nullable e `== client_id` não
        # captura linhas NULL.
        stmt = stmt.where(AgendaEvent.client_id == client_id)
    if exclude_cancelled:
        # ⚠️ **O NOME do parâmetro ficou menor que o que ele faz** (achado da revisão final da
        # Onda 2): exclui `TERMINAL_STATUSES` inteiro (`cancelled` E `done`), não só cancelado —
        # um evento marcado `done` ANTES da hora não pode continuar aparecendo no bloco de
        # "próximo compromisso" da ficha 360° como se ainda estivesse por vir. NÃO renomeado
        # para `exclude_terminal` porque `exclude_cancelled` é também o nome do QUERY PARAM
        # público (`GET /agenda/events?exclude_cancelled=true`, consumido por `BlocoDaAgenda.tsx`
        # e pelos testes de `test_agenda_por_contato.py`) — o ganho de precisão do nome não paga
        # o custo de uma migração de contrato de API só por isto. Este comentário é a correção.
        stmt = stmt.where(AgendaEvent.status.not_in(TERMINAL_STATUSES))
    # Default `False`, ao contrário de `count_events` (default `True`): a tela de Agenda chama
    # `list_events` sem este parâmetro e RENDERIZA todo evento, cancelado/feito incluso (o card
    # mostra o status); mudar o default aqui apagaria eventos do calendário sem ninguém pedir.
    # É a ficha 360° (`BlocoDaAgenda`) que passa `exclude_cancelled=True` explicitamente — ver
    # `router.py`.
    stmt = stmt.order_by(AgendaEvent.starts_at).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def count_events(
    db: Session,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    kinds: list[str] | None = None,
    exclude_cancelled: bool = True,
) -> int:
    """Conta eventos na janela SEM cap de paginação (para KPIs corretos)."""
    stmt = select(func.count(AgendaEvent.id))
    if start is not None:
        stmt = stmt.where(AgendaEvent.ends_at >= start)
    if end is not None:
        stmt = stmt.where(AgendaEvent.starts_at <= end)
    if kinds:
        stmt = stmt.where(AgendaEvent.kind.in_(kinds))
    if exclude_cancelled:
        stmt = stmt.where(AgendaEvent.status != STATUS_CANCELLED)
    return db.scalar(stmt) or 0


def get_event(db: Session, event_id: str) -> AgendaEvent:
    event = db.get(AgendaEvent, event_id)
    if event is None:
        raise AgendaError("Evento não encontrado", 404)
    return event


def update_event(
    db: Session, *, event_id: str, tenant_id: str, actor: str, data: EventUpdate,
    by_ai: bool = False,
) -> AgendaEvent:
    event = get_event(db, event_id)
    if data.title is not None:
        event.title = data.title
    if data.description is not None:
        event.description = data.description
    if data.status is not None:
        event.status = data.status
    if data.priority is not None:
        event.priority = data.priority
    if data.location is not None:
        event.location = data.location
    if data.meeting_url is not None:
        event.meeting_url = data.meeting_url
    if data.client_id is not None:
        event.client_id = data.client_id
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="agenda.event.update", target=event.id,
        is_ai=by_ai,
    )
    db.commit()
    db.refresh(event)
    return event


def cancel_event(
    db: Session, *, event_id: str, tenant_id: str, actor: str, by_ai: bool = False
) -> AgendaEvent:
    event = get_event(db, event_id)
    if event.status in TERMINAL_STATUSES:
        raise AgendaError("Evento já finalizado ou cancelado", 409)
    event.status = STATUS_CANCELLED
    # Se este evento tem um espelho no Google (Meet real vinculado), remove-o lá para não deixar
    # evento fantasma. Best-effort/não bloqueante: falha do Google não derruba o cancel local
    # (mesmo padrão de create_event). Import lazy p/ não acoplar a Agenda-núcleo à extensão.
    if event.google_event_id:
        from app.modules.google_calendar import service as gcal

        gcal.delete_meet_event(db, tenant_id=tenant_id, event=event)
    facts.record(
        db, tenant_id=tenant_id, module="agenda", kind=AGENDA_EVENTO_CANCELADO,
        title=f"Cancelado: {event.title[:100]}", actor=actor, is_ai=by_ai,
        subject_type="agenda_event", subject_id=event.id,
    )
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="agenda.event.cancel", target=event.id,
        is_ai=by_ai,
    )
    db.commit()
    db.refresh(event)
    return event


def reschedule_event(
    db: Session,
    *,
    event_id: str,
    tenant_id: str,
    actor: str,
    starts_at: datetime,
    ends_at: datetime,
    by_ai: bool = False,
) -> tuple[AgendaEvent, list[AgendaEvent]]:
    event = get_event(db, event_id)
    if event.status in TERMINAL_STATUSES:
        raise AgendaError("Não é possível remarcar evento finalizado ou cancelado", 409)
    conflicts: list[AgendaEvent] = []
    if event.kind in OCCUPYING_KINDS:
        conflicts = find_conflicts(db, starts_at, ends_at, exclude_id=event.id)
    event.starts_at = starts_at
    event.ends_at = ends_at
    # Se este evento tem um espelho no Google (Meet real vinculado), atualiza os horários lá para
    # não ficar desatualizado. Best-effort/não bloqueante: falha do Google não derruba o
    # reschedule local (mesmo padrão de create_event). Import lazy p/ não acoplar a Agenda-núcleo.
    if event.google_event_id:
        from app.modules.google_calendar import service as gcal

        gcal.patch_meet_event(db, tenant_id=tenant_id, event=event)
    facts.record(
        db, tenant_id=tenant_id, module="agenda", kind=AGENDA_EVENTO_REMARCADO,
        title=f"Remarcado: {event.title[:100]}", actor=actor, is_ai=by_ai,
        subject_type="agenda_event", subject_id=event.id,
    )
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="agenda.event.reschedule", target=event.id,
        is_ai=by_ai,
    )
    db.commit()
    db.refresh(event)
    return event, conflicts


def next_event_map(db: Session) -> dict[str, AgendaEvent]:
    """Próximo compromisso por contato, para a linha do card do Kanban.

    Consulta agregada, uma para o board inteiro — no molde de `crm_service.last_interaction_map`,
    que existe justamente porque valor derivado guardado dessincroniza. O custo não cresce com
    a quantidade de cards.

    ⚠️ O corte é `ends_at >= agora`, NÃO `starts_at >= agora`. Evento de dia inteiro tem `starts_at`
    ancorado à MEIA-NOITE — mas em qual fuso depende de QUEM criou o evento, e as duas
    convenções coexistem de propósito (achado da revisão final da Onda 2, não unificado aqui:
    virar migration de dados está fora desta onda):
      - `create_event` ancora na meia-noite REAL do fuso do TENANT (convertida p/ UTC via
        `day_window_utc` — ver a docstring dele);
      - `receivables.service.build_charge` (a população DOMINANTE que alimenta este mapa, já
        que toda cobrança nasce com evento) ancora na meia-noite UTC CRUA — ver o comentário lá.
    Nos dois casos, às 15h no fuso do tenant o `starts_at` já ficou no passado — filtrar pelo
    início esconderia o compromisso de HOJE, que é o mais relevante que existe para o card.
    Pelo fim, ele aparece o dia todo e some quando acaba, em QUALQUER das duas convenções.

    Cancelado E feito ficam de fora (`TERMINAL_STATUSES`): nenhum dos dois é próximo passo — um
    `done` adiantado pelo dono é tão "já resolvido" quanto um cancelado, para esta pergunta.

    A sessão já chega escopada por RLS (mesma convenção de `list_events`).
    """
    agora = datetime.now(UTC)
    # Mesmo padrão de `unread_client_ids` (whatsapp_inbox/service.py): `row_number()` particionado
    # por contato, ordenado por (starts_at, id), ficando com rn == 1. O desempate por `id` não é
    # decoração — dois eventos no mesmo instante fariam "o próximo" dançar entre chamadas sem ele.
    # Sem SQL condicional por dialeto: roda igual em SQLite (teste) e Postgres (produção).
    ranked = (
        select(
            AgendaEvent.id.label("id"),
            func.row_number()
            .over(
                partition_by=AgendaEvent.client_id,
                order_by=(AgendaEvent.starts_at, AgendaEvent.id),
            )
            .label("rn"),
        )
        .where(
            AgendaEvent.client_id.is_not(None),
            # `TERMINAL_STATUSES`, não só `STATUS_CANCELLED` (achado da revisão final da Onda 2):
            # um compromisso marcado `done` ANTES da hora (o dono adianta o status) não é "próximo
            # passo" nenhum — ele já aconteceu, do ponto de vista de quem preenche o card. Cancelado
            # e feito são os dois jeitos de um evento deixar de ser pendência.
            AgendaEvent.status.not_in(TERMINAL_STATUSES),
            AgendaEvent.ends_at >= agora,
        )
        .subquery()
    )
    stmt = select(AgendaEvent).join(ranked, ranked.c.id == AgendaEvent.id).where(ranked.c.rn == 1)
    return {event.client_id: event for event in db.scalars(stmt).all()}
