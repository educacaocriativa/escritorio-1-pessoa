"""Sync Google Calendar -> e1p (pull), o sentido que faltava depois da Story 4.1.

O e1p -> Google já existe e continua intocado aqui (create_meet_event/patch_meet_event/
delete_meet_event em service.py, chamados por agenda/service.py). Este módulo cobre o
CONTRÁRIO: eventos criados/editados/cancelados direto no Google Calendar do dono precisam
aparecer na Agenda do e1p.

Mecanismo: sync incremental via `syncToken` do Google (barato — a maioria das rodadas devolve
pouco ou nada). Sem `syncToken` salvo (primeira vez) ou se o Google devolver 410 (token
expirado), faz um sync completo limitado por janela (30 dias atrás / 6 meses à frente) e
estabelece um `syncToken` novo.

Sem eco: eventos aplicados aqui NUNCA disparam create_meet_event/patch_meet_event/
delete_meet_event de volta pro Google — o pull só escreve na Agenda local. Mesmo princípio de
robustez do resto do módulo (IV1/IV2): qualquer falha é capturada, logada, e NUNCA propaga.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.agenda.models import (
    KIND_GOOGLE,
    STATUS_CANCELLED,
    STATUS_DONE,
    AgendaEvent,
)
from app.modules.google_calendar.service import _HTTP_TIMEOUT, _ensure_fresh_token, get_credential

logger = logging.getLogger("e1p.google_calendar_sync")

_LIST_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
_INITIAL_SYNC_PAST_DAYS = 30
_INITIAL_SYNC_FUTURE_DAYS = 180
# Duplicado de `agenda/service.py::TERMINAL_STATUSES` de propósito — importar o `service` de lá
# traria a camada de negócio inteira (audit, facts, criação de evento) só por uma constante de
# dois valores. Mesmo padrão de `MEET_KINDS` duplicado entre `agenda/service.py` e
# `google_calendar/service.py`.
_TERMINAL_STATUSES = {STATUS_CANCELLED, STATUS_DONE}


class _SyncTokenExpired(Exception):
    """O Google devolveu 410 para o syncToken salvo — precisa refazer o sync completo."""


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def _list_params(sync_token: str | None) -> dict:
    if sync_token:
        return {"singleEvents": "true", "syncToken": sync_token}
    now = datetime.now(UTC)
    return {
        "singleEvents": "true",
        "timeMin": _iso(now - timedelta(days=_INITIAL_SYNC_PAST_DAYS)),
        "timeMax": _iso(now + timedelta(days=_INITIAL_SYNC_FUTURE_DAYS)),
    }


def _fetch_all_pages(access_token: str, base_params: dict) -> tuple[list[dict], str | None]:
    """Percorre todas as páginas. Levanta `_SyncTokenExpired` em HTTP 410 (só pode acontecer
    na 1ª página, já que só a chamada com `syncToken` pode expirar)."""
    items: list[dict] = []
    next_sync_token: str | None = None
    params = dict(base_params)
    while True:
        resp = httpx.get(
            _LIST_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code == 410:
            raise _SyncTokenExpired
        resp.raise_for_status()
        data = resp.json()
        items.extend(data.get("items", []))
        if "nextSyncToken" in data:
            next_sync_token = data["nextSyncToken"]
        page_token = data.get("nextPageToken")
        if not page_token:
            break
        params = dict(base_params)
        params["pageToken"] = page_token
    return items, next_sync_token


def _parse_google_datetime(node: dict, *, all_day: bool) -> datetime | None:
    if all_day:
        raw = node.get("date")
        if not raw:
            return None
        return datetime.fromisoformat(raw).replace(tzinfo=UTC)
    raw = node.get("dateTime")
    if not raw:
        return None
    return datetime.fromisoformat(raw)


def _apply_item(db: Session, *, tenant_id: str, item: dict, account_email: str | None) -> bool:
    """Aplica UM item da resposta do Google na Agenda local. Retorna True se algo mudou.

    `account_email` é a conta Google de onde ESTE item veio (a credencial usada em
    `pull_changes`). Carimbá-la junto do `google_event_id` é o que permite invalidar o vínculo
    depois, se o dono reconectar com outra conta — ver `service.py::upsert_credential`.
    """
    google_event_id = item.get("id")
    if not google_event_id:
        return False

    existing = db.scalars(
        select(AgendaEvent).where(AgendaEvent.google_event_id == google_event_id)
    ).first()

    if item.get("status") == "cancelled":
        if existing is None or existing.status in _TERMINAL_STATUSES:
            return False
        existing.status = STATUS_CANCELLED
        db.add(existing)
        return True

    start = item.get("start") or {}
    end = item.get("end") or {}
    all_day = "date" in start
    starts_at = _parse_google_datetime(start, all_day=all_day)
    ends_at = _parse_google_datetime(end, all_day=all_day)
    if starts_at is None or ends_at is None:
        return False  # item sem horário utilizável — não há o que gravar

    title = item.get("summary") or "(sem título)"
    description = item.get("description", "")
    location = item.get("location", "")
    meeting_url = item.get("hangoutLink") or None
    guests = [a["email"] for a in item.get("attendees", []) if a.get("email")]

    if existing is None:
        existing = AgendaEvent(
            tenant_id=tenant_id,
            title=title,
            description=description,
            kind=KIND_GOOGLE,
            source="google",
            starts_at=starts_at,
            ends_at=ends_at,
            all_day=all_day,
            location=location,
            meeting_url=meeting_url,
            guests=guests,
            google_event_id=google_event_id,
            google_account_email=account_email,
        )
    else:
        existing.title = title
        existing.description = description
        existing.starts_at = starts_at
        existing.ends_at = ends_at
        existing.all_day = all_day
        existing.location = location
        existing.meeting_url = meeting_url
        existing.guests = guests
        # Carimbo TAMBÉM no ramo de update, e não só no INSERT: é ele que AUTOCURA as linhas
        # legadas (`google_account_email IS NULL`, gravadas antes da migration 0086, que de
        # propósito não fez backfill). No primeiro sync bem-sucedido a procedência deixa de ser
        # desconhecida e a linha passa a ser protegida/invalidável como qualquer outra.
        existing.google_account_email = account_email
    db.add(existing)
    return True


def pull_changes(db: Session, *, tenant_id: str) -> int:
    """Puxa o que mudou no Google Calendar do tenant e aplica na Agenda local.

    Retorna quantos eventos locais foram criados/atualizados/cancelados. Nunca levanta: toda
    falha (sem credencial, sem token válido, rede, quota) é capturada e loga, retornando 0 —
    o worker segue para o próximo tenant/etapa sem interrupção (IV1/IV2)."""
    cred = get_credential(db)
    if cred is None:
        return 0
    try:
        access_token = _ensure_fresh_token(db, cred)
        if not access_token:
            return 0
        try:
            items, next_sync_token = _fetch_all_pages(access_token, _list_params(cred.sync_token))
        except _SyncTokenExpired:
            cred.sync_token = None
            items, next_sync_token = _fetch_all_pages(access_token, _list_params(None))

        # `or None`: `google_account_email` fica "" quando o `userinfo` falhou no callback —
        # string vazia não é um e-mail, é procedência desconhecida (mesma semântica do NULL).
        account_email = cred.google_account_email or None
        touched = 0
        for item in items:
            if _apply_item(db, tenant_id=tenant_id, item=item, account_email=account_email):
                touched += 1

        if next_sync_token:
            cred.sync_token = next_sync_token
        db.add(cred)
        db.commit()
        return touched
    except Exception:
        logger.exception("[google:pull_changes:failed] tenant=%s", tenant_id)
        return 0
