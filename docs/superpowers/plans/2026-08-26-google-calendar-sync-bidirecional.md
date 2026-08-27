# Google Calendar — sincronização bidirecional Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Google Calendar events created/edited/cancelled directly in the owner's Google Calendar app show up in the e1p Agenda (pull), completing the two-way sync — the e1p→Google direction (create/reschedule/cancel) already exists and works.

**Architecture:** A new `google_calendar/sync.py` module does incremental sync via Google's `syncToken` (falling back to a bounded full sync on first run or token expiry), called by a new stage in the existing `app.worker` sweep (runs every ~60s, per tenant). Imported events land as `AgendaEvent(kind="google")` matched by `google_event_id`; the sync never re-propagates what it just read back to Google (no echo). Separately, the existing e1p→Google push widens to also mirror `bloqueio` events (without generating a Meet link), and the Agenda's event-detail modal gains a small "link to CRM client" control since it doesn't exist yet (a gap found while grounding this plan — the design spec assumed it existed).

**Tech Stack:** FastAPI + SQLAlchemy 2 + Alembic (backend), React + Vite + TypeScript + Tailwind (frontend), `httpx` for the Google Calendar REST API (no SDK, matching the rest of the codebase), pytest + vitest for tests.

**Spec:** `docs/superpowers/specs/2026-08-26-google-calendar-sync-bidirecional-design.md`

## Global Constraints

- RLS is the ONLY tenant-isolation guard — never add a manual `tenant_id` filter to a query; the session is already scoped (Golden Rule #1, CLAUDE.md §3).
- Money is never involved here; no `amount_cents` handling needed.
- Failures calling Google must NEVER break local operations — always capture, log via `logger.exception`, degrade gracefully (existing convention in `google_calendar/service.py`).
- New migration number: **`0081`**, `down_revision="0080"` (current head, confirmed 2026-08-26).
- Initial (bounded) sync window: 30 days in the past, 180 days in the future.
- PT-BR for user-facing text and domain comments; English for identifiers.
- After finishing, add a CLAUDE.md entry (§6, replacing the stale "PENDENTE" line) per repo convention (CLAUDE.md §5 step 4 — the entry is as mandatory as the tests).

---

## File Structure

- Modify: `apps/api/app/modules/agenda/models.py` — add `KIND_GOOGLE` constant, `ALL_KINDS`/`OCCUPYING_KINDS`.
- Create: `apps/api/migrations/versions/0081_google_calendar_sync.py` — `google_credentials.sync_token` column + unique index on `agenda_events(tenant_id, google_event_id)`.
- Modify: `apps/api/app/modules/google_calendar/models.py` — add `sync_token` column to `GoogleCredential`.
- Modify: `apps/api/app/modules/google_calendar/service.py` — `PUSHED_KINDS` constant; `create_meet_event` decides `conferenceData` internally from `MEET_KINDS`.
- Modify: `apps/api/app/modules/agenda/service.py` — `create_event` uses `PUSHED_KINDS` instead of `MEET_KINDS`.
- Create: `apps/api/app/modules/google_calendar/sync.py` — `pull_changes(db, *, tenant_id) -> int`, the pull-side sync engine.
- Modify: `apps/api/app/worker.py` — new "Etapa 7" calling `sync.pull_changes` per tenant.
- Create: `apps/api/tests/test_google_calendar_sync.py` — unit tests for the new sync engine (SQLite, mocked HTTP).
- Create: `apps/api/tests/test_google_calendar_sync_rls.py` — real-Postgres test for the unique index (`rls_e2e`).
- Modify: `apps/api/tests/test_agenda.py` — new case: `bloqueio` is pushed without `conferenceData`.
- Modify: `apps/api/tests/test_worker.py` — new cases for the Etapa 7 wiring.
- Modify: `apps/web/src/features/agenda/AgendaPage.tsx` — `eventColor` gains a `"google"` case; `EventDetailModal` gains a `ClienteVinculo` client-link control.
- Modify: `apps/web/src/features/agenda/AgendaPage.test.tsx` — tests for the client-link control.
- Modify: `f:\Projetos\e1p\escritorio-1-pessoa\CLAUDE.md` — replace the stale roadmap line for the Google integration.

---

### Task 1: `KIND_GOOGLE` in the Agenda model

**Files:**
- Modify: `apps/api/app/modules/agenda/models.py`
- Test: `apps/api/tests/test_agenda.py`

**Interfaces:**
- Produces: `KIND_GOOGLE = "google"` (importable from `app.modules.agenda.models`), included in `ALL_KINDS` and `OCCUPYING_KINDS`.

- [ ] **Step 1: Write the failing test**

Add to `apps/api/tests/test_agenda.py` (near the other kind-validation tests):

```python
def test_kind_google_is_valid_and_occupies_time(client: TestClient, headers):
    resp = client.post(
        "/agenda/events",
        json={
            "title": "Aniversário de Fulano",
            "kind": "google",
            "starts_at": "2026-09-10T10:00:00Z",
            "ends_at": "2026-09-10T11:00:00Z",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    # ocupa horário → um segundo evento no mesmo intervalo vem com conflito.
    resp2 = client.post(
        "/agenda/events",
        json={
            "title": "Outro compromisso",
            "kind": "atendimento",
            "starts_at": "2026-09-10T10:30:00Z",
            "ends_at": "2026-09-10T11:30:00Z",
        },
        headers=headers,
    )
    assert resp2.status_code == 201, resp2.text
    assert len(resp2.json()["conflicts"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && python -m pytest tests/test_agenda.py::test_kind_google_is_valid_and_occupies_time -v`
Expected: FAIL with `422` (kind inválido: google), because `"google"` isn't in `ALL_KINDS` yet.

- [ ] **Step 3: Write minimal implementation**

In `apps/api/app/modules/agenda/models.py`, add the constant next to the other `KIND_*` constants (after `KIND_LEMBRETE = "lembrete"`):

```python
# Evento espelhado a partir do Google Calendar (sync Google → e1p) — não tem tipo de negócio do
# e1p (não é reunião com cliente nem cobrança); ocupa horário de verdade na agenda do dono.
KIND_GOOGLE = "google"
```

Update `ALL_KINDS` and `OCCUPYING_KINDS` right below:

```python
ALL_KINDS = {
    KIND_ATENDIMENTO, KIND_REUNIAO, KIND_AUDIENCIA, KIND_BLOQUEIO,
    KIND_PRAZO, KIND_COBRANCA_RECEBER, KIND_COBRANCA_PAGAR, KIND_LEMBRETE, KIND_GOOGLE,
}
# Eventos que ocupam um intervalo de tempo (entram na checagem de conflito de agenda).
OCCUPYING_KINDS = {KIND_ATENDIMENTO, KIND_REUNIAO, KIND_AUDIENCIA, KIND_BLOQUEIO, KIND_GOOGLE}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && python -m pytest tests/test_agenda.py::test_kind_google_is_valid_and_occupies_time -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/modules/agenda/models.py apps/api/tests/test_agenda.py
git commit -m "feat: agenda ganha o kind \"google\" (Google Calendar Sync, passo 1)"
```

---

### Task 2: migration 0081 — `sync_token` + índice único

**Files:**
- Modify: `apps/api/app/modules/google_calendar/models.py`
- Create: `apps/api/migrations/versions/0081_google_calendar_sync.py`
- Test: `apps/api/tests/test_google_calendar_sync.py` (created here, extended in Task 3)

**Interfaces:**
- Consumes: nothing new.
- Produces: `GoogleCredential.sync_token: str | None`. DB-level unique index `ix_agenda_events_tenant_google_event_id` on `(tenant_id, google_event_id)` where `google_event_id IS NOT NULL`.

⚠️ **The unique index is validated only in Task 6 (`rls_e2e`), not here.** The `db` fixture used
by the rest of the backend suite builds its schema via `Base.metadata.create_all(engine)`
(`conftest.py:145`) — straight from the SQLAlchemy model declarations. A raw `op.create_index(...)`
written only inside a migration script is **never** applied to that SQLite schema (this repo has
no existing precedent of declaring a partial-unique index on the model itself — `grep -rn
"postgresql_where\|sqlite_where" apps/api/app/modules` returns nothing; every existing partial-
unique index in this codebase, e.g. `bank_transactions`'s idempotency index, is validated the same
way: only under `rls_e2e`/real Postgres). Follow the same convention here — don't try to assert the
uniqueness under SQLite.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_google_calendar_sync.py`:

```python
"""Testes do sync Google Calendar -> e1p (pull). Todas as chamadas HTTP são MOCKADAS.

O índice único de `google_event_id` (migration 0081) é validado à parte, contra Postgres real,
em test_google_calendar_sync_rls.py — a suíte SQLite deste arquivo não o exercita (ver Task 2
do plano: `Base.metadata.create_all` não aplica índice criado só via `op.create_index`)."""
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.modules.google_calendar.models import GoogleCredential

TENANT = "t" * 12


def _connect_google(db: Session, *, sync_token: str | None = None) -> GoogleCredential:
    cred = GoogleCredential(
        tenant_id=TENANT,
        google_account_email="owner@gmail.com",
        access_token="valid-access-token",
        refresh_token="valid-refresh-token",
        token_expiry=datetime.now(UTC) + timedelta(hours=1),
        sync_token=sync_token,
    )
    db.add(cred)
    db.commit()
    db.refresh(cred)
    return cred


def test_sync_token_column_roundtrips(db: Session):
    cred = _connect_google(db, sync_token="token-abc")
    db.expire_all()
    fresh = db.get(GoogleCredential, cred.id)
    assert fresh.sync_token == "token-abc"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && python -m pytest tests/test_google_calendar_sync.py -v`
Expected: FAIL — `TypeError: 'sync_token' is an invalid keyword argument for GoogleCredential` (the column doesn't exist on the model yet).

- [ ] **Step 3: Write minimal implementation**

In `apps/api/app/modules/google_calendar/models.py`, add the column at the end of `GoogleCredential`:

```python
    # Cursor de sincronização incremental do Google (nextSyncToken). NULL = nunca sincronizado
    # (ou expirou e foi limpo) — a próxima rodada faz um sync completo limitado por janela.
    sync_token: Mapped[str | None] = mapped_column(Text, nullable=True)
```

This requires importing `Text` — update the sqlalchemy import line at the top of the file:

```python
from sqlalchemy import DateTime, String, Text
```

Create `apps/api/migrations/versions/0081_google_calendar_sync.py`:

```python
"""google_calendar sync: google_credentials.sync_token + índice único de google_event_id

Revision ID: 0081
Revises: 0080
Create Date: 2026-08-26

Duas peças, as duas DDL puro, sem UPDATE nenhum — a armadilha do backfill sob FORCE RLS
(0046/0066/0067/0068/0069/0073) não se aplica aqui:

1. `google_credentials.sync_token` — o cursor de sync incremental do Google (nextSyncToken),
   um por tenant, na mesma linha que já guarda os tokens OAuth. NULL = nunca sincronizado.
2. Índice único parcial em `agenda_events (tenant_id, google_event_id)` — hoje não existe
   nenhum. Enquanto `google_event_id` só era escrito pelo e1p (push), a unicidade vinha da
   lógica de criação; agora que o sync incremental (pull) pode reprocessar uma página em caso
   de retry, uma segunda escrita do mesmo `google_event_id` tem que ser REJEITADA em vez de
   duplicar o evento. `tenant_id` na FRENTE do índice porque índice único é global e não
   respeita RLS (lição da Story 8.2, CLAUDE.md §Epic 8).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0081"
down_revision: str | None = "0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("google_credentials", sa.Column("sync_token", sa.Text(), nullable=True))
    op.create_index(
        "ix_agenda_events_tenant_google_event_id",
        "agenda_events",
        ["tenant_id", "google_event_id"],
        unique=True,
        postgresql_where=sa.text("google_event_id IS NOT NULL"),
        sqlite_where=sa.text("google_event_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_agenda_events_tenant_google_event_id", table_name="agenda_events")
    op.drop_column("google_credentials", "sync_token")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && python -m pytest tests/test_google_calendar_sync.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/modules/google_calendar/models.py apps/api/migrations/versions/0081_google_calendar_sync.py apps/api/tests/test_google_calendar_sync.py
git commit -m "feat: migration 0081 — sync_token do Google + índice único de google_event_id"
```

---

### Task 3: `google_calendar/sync.py` — o motor de pull

**Files:**
- Modify: `apps/api/app/modules/google_calendar/service.py` (small addition: reuse `_ensure_fresh_token`, `_iso`, `get_credential`, `_HTTP_TIMEOUT` — no signature changes)
- Create: `apps/api/app/modules/google_calendar/sync.py`
- Test: `apps/api/tests/test_google_calendar_sync.py` (extended)

**Interfaces:**
- Consumes: `google_calendar.service.get_credential(db) -> GoogleCredential | None`, `google_calendar.service._ensure_fresh_token(db, cred) -> str | None`, `google_calendar.service._HTTP_TIMEOUT`, `agenda.models.{AgendaEvent, KIND_GOOGLE, STATUS_CANCELLED, TERMINAL_STATUSES}`.
- Produces: `sync.pull_changes(db: Session, *, tenant_id: str) -> int` — returns how many local events were touched (created/updated/cancelled). Never raises.

- [ ] **Step 1: Write the failing tests**

Append to `apps/api/tests/test_google_calendar_sync.py`. Add these to the imports at the TOP of
the file (alongside the ones from Task 2 — `httpx`, `select`, and `AgendaEvent` aren't imported
yet there):

```python
import httpx
from sqlalchemy import select

from app.modules.agenda.models import STATUS_CANCELLED, AgendaEvent
```

Then append the rest below the existing `_connect_google` helper:

```python
from app.modules.google_calendar import sync


class _FakeResp:
    def __init__(self, status_code: int, data: dict | None = None):
        self.status_code = status_code
        self._data = data or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)

    def json(self) -> dict:
        return self._data


def test_pull_changes_noop_without_credential(db: Session):
    assert sync.pull_changes(db, tenant_id=TENANT) == 0


def test_first_sync_creates_events_and_saves_token(db: Session, monkeypatch):
    _connect_google(db)
    payload = {
        "items": [
            {
                "id": "gcal-1",
                "summary": "Aniversário de Vera",
                "start": {"date": "2026-09-10"},
                "end": {"date": "2026-09-11"},
            },
            {
                "id": "gcal-2",
                "summary": "Visita",
                "start": {"dateTime": "2026-09-12T13:00:00-03:00"},
                "end": {"dateTime": "2026-09-12T14:00:00-03:00"},
                "hangoutLink": "https://meet.google.com/abc-defg-hij",
                "attendees": [{"email": "cliente@example.com"}],
            },
        ],
        "nextSyncToken": "token-v1",
    }

    def fake_get(url: str, **kw):
        assert "syncToken" not in kw.get("params", {})  # primeira vez: sem cursor
        return _FakeResp(200, payload)

    monkeypatch.setattr(httpx, "get", fake_get)

    touched = sync.pull_changes(db, tenant_id=TENANT)
    assert touched == 2

    events = db.scalars(select(AgendaEvent).order_by(AgendaEvent.title)).all()
    assert [e.title for e in events] == ["Aniversário de Vera", "Visita"]
    assert events[0].kind == "google"
    assert events[0].all_day is True
    assert events[1].all_day is False
    assert events[1].meeting_url == "https://meet.google.com/abc-defg-hij"
    assert events[1].guests == ["cliente@example.com"]

    cred = db.scalars(select(GoogleCredential)).first()
    assert cred.sync_token == "token-v1"


def test_incremental_sync_uses_saved_token(db: Session, monkeypatch):
    _connect_google(db, sync_token="token-v1")
    captured = {}

    def fake_get(url: str, **kw):
        captured["params"] = kw.get("params", {})
        return _FakeResp(200, {"items": [], "nextSyncToken": "token-v2"})

    monkeypatch.setattr(httpx, "get", fake_get)

    sync.pull_changes(db, tenant_id=TENANT)
    assert captured["params"]["syncToken"] == "token-v1"
    assert "timeMin" not in captured["params"]


def test_cancelled_item_cancels_local_event_without_calling_google(db: Session, monkeypatch):
    _connect_google(db, sync_token="token-v1")
    db.add(
        AgendaEvent(
            tenant_id=TENANT,
            title="Reunião",
            kind="google",
            starts_at=datetime(2026, 9, 12, 13, 0, tzinfo=UTC),
            ends_at=datetime(2026, 9, 12, 14, 0, tzinfo=UTC),
            google_event_id="gcal-2",
        )
    )
    db.commit()

    delete_calls = []
    monkeypatch.setattr(httpx, "delete", lambda *a, **kw: delete_calls.append(1))

    def fake_get(url: str, **kw):
        return _FakeResp(
            200, {"items": [{"id": "gcal-2", "status": "cancelled"}], "nextSyncToken": "token-v2"}
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    touched = sync.pull_changes(db, tenant_id=TENANT)
    assert touched == 1
    event = db.scalars(select(AgendaEvent).where(AgendaEvent.google_event_id == "gcal-2")).first()
    assert event.status == STATUS_CANCELLED
    assert delete_calls == []  # sem eco: não tenta cancelar de volta no Google


def test_existing_event_updates_without_calling_google(db: Session, monkeypatch):
    _connect_google(db, sync_token="token-v1")
    db.add(
        AgendaEvent(
            tenant_id=TENANT,
            title="Título antigo",
            kind="google",
            starts_at=datetime(2026, 9, 12, 13, 0, tzinfo=UTC),
            ends_at=datetime(2026, 9, 12, 14, 0, tzinfo=UTC),
            google_event_id="gcal-3",
        )
    )
    db.commit()

    patch_calls = []
    monkeypatch.setattr(httpx, "patch", lambda *a, **kw: patch_calls.append(1))

    def fake_get(url: str, **kw):
        return _FakeResp(
            200,
            {
                "items": [
                    {
                        "id": "gcal-3",
                        "summary": "Título novo",
                        "start": {"dateTime": "2026-09-12T15:00:00-03:00"},
                        "end": {"dateTime": "2026-09-12T16:00:00-03:00"},
                    }
                ],
                "nextSyncToken": "token-v2",
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    sync.pull_changes(db, tenant_id=TENANT)
    event = db.scalars(select(AgendaEvent).where(AgendaEvent.google_event_id == "gcal-3")).first()
    assert event.title == "Título novo"
    assert patch_calls == []  # sem eco: não repropaga a mudança de volta pro Google


def test_expired_sync_token_falls_back_to_full_sync(db: Session, monkeypatch):
    cred = _connect_google(db, sync_token="expired-token")
    calls = []

    def fake_get(url: str, **kw):
        params = kw.get("params", {})
        calls.append(params)
        if "syncToken" in params:
            return _FakeResp(410, {})
        return _FakeResp(200, {"items": [], "nextSyncToken": "fresh-token"})

    monkeypatch.setattr(httpx, "get", fake_get)

    sync.pull_changes(db, tenant_id=TENANT)
    assert len(calls) == 2
    assert "syncToken" in calls[0]
    assert "timeMin" in calls[1]
    db.refresh(cred)
    assert cred.sync_token == "fresh-token"


def test_network_failure_returns_zero_and_keeps_token(db: Session, monkeypatch):
    cred = _connect_google(db, sync_token="token-v1")

    def fake_get(url: str, **kw):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "get", fake_get)

    assert sync.pull_changes(db, tenant_id=TENANT) == 0
    db.refresh(cred)
    assert cred.sync_token == "token-v1"  # não corrompe o cursor numa falha
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/api && python -m pytest tests/test_google_calendar_sync.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.google_calendar.sync'`.

- [ ] **Step 3: Write the implementation**

Create `apps/api/app/modules/google_calendar/sync.py`:

```python
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
from app.modules.google_calendar.models import GoogleCredential
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


def _apply_item(db: Session, *, tenant_id: str, item: dict) -> bool:
    """Aplica UM item da resposta do Google na Agenda local. Retorna True se algo mudou."""
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

        touched = 0
        for item in items:
            if _apply_item(db, tenant_id=tenant_id, item=item):
                touched += 1

        if next_sync_token:
            cred.sync_token = next_sync_token
        db.add(cred)
        db.commit()
        return touched
    except Exception:
        logger.exception("[google:pull_changes:failed] tenant=%s", tenant_id)
        return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/api && python -m pytest tests/test_google_calendar_sync.py -v`
Expected: PASS (all 9 tests: the unique-index test from Task 2 plus the 8 new ones).

- [ ] **Step 5: Run the full backend suite to check for regressions**

Run: `cd apps/api && python -m pytest -q`
Expected: same pass count as before plus the new tests, zero failures.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/google_calendar/sync.py apps/api/tests/test_google_calendar_sync.py
git commit -m "feat: google_calendar.sync.pull_changes — sync incremental Google -> e1p"
```

---

### Task 4: extend the push side to mirror `bloqueio` (sem Meet)

**Files:**
- Modify: `apps/api/app/modules/google_calendar/service.py`
- Modify: `apps/api/app/modules/agenda/service.py`
- Test: `apps/api/tests/test_google_calendar_hardening.py`

**Interfaces:**
- Consumes: `agenda.models.KIND_BLOQUEIO`.
- Produces: `google_calendar.service.PUSHED_KINDS = {"reuniao", "atendimento", "audiencia", "bloqueio"}`. `create_meet_event` now decides internally whether to request `conferenceData` (only for `MEET_KINDS`), so it's safe to call for any `PUSHED_KINDS` member.

- [ ] **Step 1: Write the failing test**

`test_google_calendar_hardening.py` tests `agenda.service` functions directly (no HTTP `client`
fixture in this file) — write the new test the same way, matching `_make_event`/`_connect_google`
already used by the reschedule/cancel tests above it in the file. Append:

```python
def test_bloqueio_is_pushed_without_conference_data(db: Session, monkeypatch):
    """Bloqueio de horário vira evento espelho no Google, mas SEM gerar Meet — não é reunião."""
    _connect_google(db)
    captured = {}

    def fake_post(url: str, **kw):
        captured["json"] = kw.get("json")
        return _FakeResp(200, {"id": "gcal-bloqueio-1"})

    monkeypatch.setattr(httpx, "post", fake_post)

    from app.modules.agenda import service as agenda
    from app.modules.agenda.schemas import EventCreate

    event, _ = agenda.create_event(
        db,
        tenant_id=TENANT,
        actor="user-1",
        by_ai=False,
        data=EventCreate(
            title="Bloqueio da tarde",
            kind="bloqueio",
            starts_at=datetime(2026, 9, 10, 13, 0, tzinfo=UTC),
            ends_at=datetime(2026, 9, 10, 17, 0, tzinfo=UTC),
        ),
    )
    assert event.google_event_id == "gcal-bloqueio-1"
    assert "conferenceData" not in captured["json"]
```

This requires `_FakeResp` to also return the event id via `.json()`. Extend the existing `_FakeResp` class in that file (it currently only has `status_code`/`raise_for_status`) — add a `json()` method:

```python
class _FakeResp:
    def __init__(self, status_code: int = 200, data: dict | None = None):
        self.status_code = status_code
        self._data = data or {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._data
```

And use `_FakeResp(200, {"id": "gcal-bloqueio-1"})` in the new test's `fake_post`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && python -m pytest tests/test_google_calendar_hardening.py::test_bloqueio_is_pushed_without_conference_data -v`
Expected: FAIL — `event.google_event_id` is `None` because `create_event` only calls `create_meet_event` for `event.kind in MEET_KINDS`, and `"bloqueio"` isn't in it.

- [ ] **Step 3: Write the implementation**

In `apps/api/app/modules/google_calendar/service.py`, right after `MEET_KINDS`:

```python
# Tipos de evento onde "reunião" faz sentido (geram Meet). Bloqueios/prazos/cobranças não.
MEET_KINDS = {"reuniao", "atendimento", "audiencia"}
# Tipos de evento espelhados no Google (create/reschedule/cancel), com ou sem Meet. Bloqueio
# ocupa horário de verdade na agenda do dono e por isso é espelhado — mas não é reunião, então
# não pede conferenceData (ver create_meet_event abaixo).
PUSHED_KINDS = MEET_KINDS | {"bloqueio"}
```

Update `create_meet_event`'s body construction to build `conferenceData` conditionally:

```python
        body = {
            "summary": event.title,
            "description": event.description or "",
            "start": {"dateTime": _iso(event.starts_at)},
            "end": {"dateTime": _iso(event.ends_at)},
            "attendees": [{"email": g} for g in (event.guests or [])],
        }
        if event.kind in MEET_KINDS:
            body["conferenceData"] = {
                "createRequest": {
                    "requestId": uuid.uuid4().hex,
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
```

(Replace the existing `body = {...}` literal that always included `"conferenceData"` — the rest of the function is unchanged.)

`apps/api/app/modules/agenda/service.py` does **not** import `MEET_KINDS` from `google_calendar` —
it keeps its own local copy (`MEET_KINDS = {KIND_REUNIAO, KIND_ATENDIMENTO, KIND_AUDIENCIA}`, line
29), duplicated by design so the Agenda-core module never has a real (non-lazy) import of the
optional Google integration. Follow the same pattern: add a local `PUSHED_KINDS` here too.

Add `KIND_BLOQUEIO` to the existing `from app.modules.agenda.models import (...)` block (the one
that already imports `KIND_ATENDIMENTO, KIND_AUDIENCIA, KIND_REUNIAO, OCCUPYING_KINDS, ...`):

```python
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
```

Right after the existing `MEET_KINDS = {KIND_REUNIAO, KIND_ATENDIMENTO, KIND_AUDIENCIA}` line, add:

```python
# Tipos espelhados no Google (create/reschedule/cancel), com ou sem Meet — mesmo conjunto de
# `google_calendar/service.py::PUSHED_KINDS`, mantido local de propósito (o módulo-núcleo Agenda
# não tem import real da integração opcional, só o lazy dentro da função abaixo).
PUSHED_KINDS = MEET_KINDS | {KIND_BLOQUEIO}
```

And update the condition inside `create_event`:

```python
    if event.kind in MEET_KINDS and not data.meeting_url:
```

becomes

```python
    if event.kind in PUSHED_KINDS and not data.meeting_url:
```

(the `from app.modules.google_calendar import service as gcal` lazy import right below stays
exactly as is.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && python -m pytest tests/test_google_calendar_hardening.py -v tests/test_google_calendar.py -v`
Expected: PASS — the new test passes, and the pre-existing Meet-generation tests in `test_google_calendar.py` still pass unchanged (they exercise `reuniao`/`atendimento`, which still get `conferenceData`).

- [ ] **Step 5: Run the full backend suite**

Run: `cd apps/api && python -m pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/google_calendar/service.py apps/api/app/modules/agenda/service.py apps/api/tests/test_google_calendar_hardening.py
git commit -m "feat: bloqueio de horário passa a ser espelhado no Google (sem Meet)"
```

---

### Task 5: liga o pull no worker (Etapa 7)

**Files:**
- Modify: `apps/api/app/worker.py`
- Test: `apps/api/tests/test_worker.py`

**Interfaces:**
- Consumes: `google_calendar.sync.pull_changes(db, *, tenant_id) -> int` (Task 3).
- Produces: `run_sweep(...)` result dict gains `"google_events_synced": int`.

- [ ] **Step 1: Write the failing tests**

Append to `apps/api/tests/test_worker.py`:

```python
from app.modules.google_calendar import sync as google_calendar_sync


def test_run_sweep_syncs_google_calendar(client: TestClient, db, monkeypatch):
    token = client.post("/auth/register", json={
        "legal_name": "Google Sync SA", "document": "11122233000181", "slug": "googlesyncsa",
        "email": "gsync@example.com", "name": "Dona Sync", "password": "senha-bem-comprida",
    }).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/auth/me", headers=headers).status_code == 200

    monkeypatch.setattr(google_calendar_sync, "pull_changes", lambda db, *, tenant_id: 3)

    cm = _cm_factory(db)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm)
    assert result["google_events_synced"] == 3


def test_run_sweep_isolates_google_sync_failure(client: TestClient, db, monkeypatch):
    token = client.post("/auth/register", json={
        "legal_name": "Google Fail SA", "document": "22233344000172", "slug": "googlefailsa",
        "email": "gfail@example.com", "name": "Dona Fail", "password": "senha-bem-comprida",
    }).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/auth/me", headers=headers).status_code == 200

    def _raise(db, *, tenant_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(google_calendar_sync, "pull_changes", _raise)

    cm = _cm_factory(db)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm)
    assert result["google_events_synced"] == 0
    assert any(e["stage"] == "google_calendar_sync" for e in result["errors"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/api && python -m pytest tests/test_worker.py::test_run_sweep_syncs_google_calendar tests/test_worker.py::test_run_sweep_isolates_google_sync_failure -v`
Expected: FAIL — `KeyError: 'google_events_synced'` (the key doesn't exist in the result dict yet).

- [ ] **Step 3: Write the implementation**

In `apps/api/app/worker.py`, add the import near the other module-level service imports:

```python
from app.modules.google_calendar import sync as google_calendar_sync
```

In `run_sweep`'s `result` dict initializer, add the counter right after `"briefings_gerados": 0,`:

```python
        # Story do Google Calendar Sync — quantos eventos locais este sweep tocou (criou,
        # atualizou ou cancelou) puxando do Google Calendar do tenant.
        "google_events_synced": 0,
```

Add the new stage inside the `for tenant_id in tenant_ids:` loop, right after Etapa 6 (the Vima briefing block), before the closing of the loop:

```python
        # Etapa 7 — sincroniza o Google Calendar do tenant (pull), sessão SEPARADA das outras
        # seis. Tenant sem Google conectado: `pull_changes` retorna 0 sem chamada HTTP nenhuma.
        try:
            with tenant_session_factory(tenant_id) as db:
                synced = google_calendar_sync.pull_changes(db, tenant_id=tenant_id)
            result["google_events_synced"] += synced
        except Exception as exc:  # noqa: BLE001 — idem: isola a falha por tenant (IV2)
            logger.exception("[worker] sync do google calendar falhou tenant=%s", tenant_id)
            result["errors"].append(
                {"tenant_id": tenant_id, "stage": "google_calendar_sync", "error": str(exc)}
            )
```

Update the final `logger.info` call to include the new counter (add `google_eventos_sincronizados=%s` to the format string and `result["google_events_synced"]` to the args, in the same position/order style as the other counters).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/api && python -m pytest tests/test_worker.py -v`
Expected: PASS (all worker tests, including the two new ones).

- [ ] **Step 5: Run the full backend suite**

Run: `cd apps/api && python -m pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/worker.py apps/api/tests/test_worker.py
git commit -m "feat: worker ganha a Etapa 7 — puxa o Google Calendar de cada tenant conectado"
```

---

### Task 6: validação de migration contra Postgres real (`rls_e2e`)

**Files:**
- Create: `apps/api/tests/test_google_calendar_sync_rls.py` (marked `rls_e2e`, runs against real Postgres)

**Interfaces:**
- Consumes: the migration from Task 2, run via `alembic upgrade head` as the non-superuser `e1p_app` role (existing test infra pattern, mirrored from `test_receipts_rls.py`).

There's no shared `rls_e2e` fixture in this repo — every `rls_e2e` test file is self-contained,
spinning up its own `testcontainers.postgres.PostgresContainer`, bootstrapping the `e1p_app` role,
and running `alembic upgrade head` against it (see `apps/api/tests/test_receipts_rls.py`, lines
1–100). Follow that exact pattern.

- [ ] **Step 1: Write the test**

Create `apps/api/tests/test_google_calendar_sync_rls.py` (own file, matching the one-test-module-
per-concern convention of `test_receipts_rls.py`/`test_cost_centers_rls.py`):

```python
"""Confirma o índice único da migration 0081 contra Postgres REAL — SQLite não distingue um
índice parcial mal escrito (`sqlite_where` por engano em vez de `postgresql_where`) de um
correto; os dois passam no `db` fixture em memória e só o Postgres real prova a sintaxe.

Mesmo bootstrap de test_receipts_rls.py: engine "cru" da URL do container, migrations aplicadas
com `alembic upgrade head` como `e1p_app`. Marcado `rls_e2e`: NÃO roda no `pytest -q`, só no job
`cross-tenant-rls` do CI ou manualmente com Docker (`pytest -m rls_e2e`).
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("testcontainers.postgres")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from testcontainers.postgres import PostgresContainer  # noqa: E402

pytestmark = pytest.mark.rls_e2e

_ROOT_USER = "e1p_root"
_ROOT_PASS = "rootpass"  # noqa: S105 (senha efêmera do container de teste)
_APP_PASS = "e1ppass"  # noqa: S105 (senha efêmera do papel de app no container de teste)
_DB_NAME = "e1pdb"
_API_DIR = Path(__file__).resolve().parents[1]


def _bootstrap_rls_role(super_url: str) -> None:
    engine = create_engine(super_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text(f"CREATE ROLE e1p_app WITH LOGIN PASSWORD '{_APP_PASS}' NOSUPERUSER"))
            conn.execute(text(f"GRANT ALL PRIVILEGES ON DATABASE {_DB_NAME} TO e1p_app"))
            conn.execute(text("GRANT ALL ON SCHEMA public TO e1p_app"))
    finally:
        engine.dispose()


def _run_migrations_as_app(app_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    from app.config import settings

    original_url = settings.database_url
    settings.database_url = app_url
    try:
        cfg = Config(str(_API_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(_API_DIR / "migrations"))
        command.upgrade(cfg, "head")
    finally:
        settings.database_url = original_url


@contextmanager
def _tenant_session(app_url: str, tenant_id: str):
    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            conn.commit()
            session = Session(bind=conn)
            try:
                yield session
            finally:
                session.close()
    finally:
        engine.dispose()


def test_google_event_id_unique_index_enforced_on_real_postgres() -> None:
    from app.modules.agenda.models import AgendaEvent

    with PostgresContainer(
        "postgres:16-alpine",
        username=_ROOT_USER,
        password=_ROOT_PASS,
        dbname=_DB_NAME,
        driver="psycopg",
    ) as pg:
        host = pg.get_container_host_ip()
        port = pg.get_exposed_port(5432)
        super_url = f"postgresql+psycopg://{_ROOT_USER}:{_ROOT_PASS}@{host}:{port}/{_DB_NAME}"
        app_url = f"postgresql+psycopg://e1p_app:{_APP_PASS}@{host}:{port}/{_DB_NAME}"

        _bootstrap_rls_role(super_url)
        _run_migrations_as_app(app_url)

        tenant_a = str(uuid4())
        with _tenant_session(app_url, tenant_a) as session:
            session.add(
                AgendaEvent(
                    tenant_id=tenant_a,
                    title="Um",
                    kind="google",
                    starts_at=datetime(2026, 9, 10, 10, 0, tzinfo=UTC),
                    ends_at=datetime(2026, 9, 10, 11, 0, tzinfo=UTC),
                    google_event_id="pg-dup",
                )
            )
            session.commit()

            session.add(
                AgendaEvent(
                    tenant_id=tenant_a,
                    title="Dois",
                    kind="google",
                    starts_at=datetime(2026, 9, 11, 10, 0, tzinfo=UTC),
                    ends_at=datetime(2026, 9, 11, 11, 0, tzinfo=UTC),
                    google_event_id="pg-dup",
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
```

- [ ] **Step 2: Run it**

Run: `cd apps/api && python -m pytest tests/test_google_calendar_sync_rls.py -m rls_e2e -v`

Requires Docker (testcontainers) — same preconditions as any other `rls_e2e` test in this repo (CLAUDE.md §5: `pytest -m rls_e2e`, ~10s, run locally before considering the task done — it does NOT run in the default `pytest -q`).

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/api/tests/test_google_calendar_sync_rls.py
git commit -m "test: valida o índice único da migration 0081 contra Postgres real"
```

---

### Task 7: frontend — cor/rótulo do kind "google" na Agenda

**Files:**
- Modify: `apps/web/src/features/agenda/AgendaPage.tsx`
- Test: `apps/web/src/features/agenda/AgendaPage.test.tsx`

**Interfaces:**
- Consumes: `AgendaEvent.kind === "google"` (already typed as `string` in shared-types — no type change needed).
- Produces: nothing new consumed elsewhere; purely visual.

- [ ] **Step 1: Write the failing test**

Add to `apps/web/src/features/agenda/AgendaPage.test.tsx`:

```typescript
it("evento kind=google recebe cor neutra própria no chip do mês", async () => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/agenda/events") {
      return Promise.resolve({
        data: [
          {
            id: "ev-google-1",
            tenant_id: "t1",
            title: "Aniversário de Vera",
            description: "",
            kind: "google",
            status: "scheduled",
            priority: "normal",
            source: "google",
            starts_at: new Date().toISOString(),
            ends_at: new Date(Date.now() + 3600_000).toISOString(),
            all_day: true,
            location: "",
            meeting_url: null,
            guests: [],
            amount_cents: null,
            external_ref: null,
            google_event_id: "gcal-1",
            client_id: null,
            client_name: null,
            created_by_ai: false,
            created_at: new Date().toISOString(),
          },
        ],
      } as never);
    }
    return Promise.resolve({ data: [] } as never);
  });
  renderPage();
  const chip = await screen.findByTestId("chip-evento-ev-google-1");
  expect(chip.className).toContain("bg-neutral-200");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && pnpm vitest run src/features/agenda/AgendaPage.test.tsx -t "kind=google"`
Expected: FAIL — the chip falls through to the default `"bg-primary-100 text-primary-700"` branch, not `bg-neutral-200`.

- [ ] **Step 3: Write the implementation**

In `apps/web/src/features/agenda/AgendaPage.tsx`, add a case to `eventColor` right before the final `return "bg-primary-100 text-primary-700";`:

```typescript
  if (e.kind === "google") return "bg-neutral-200 text-neutral-700";
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/web && pnpm vitest run src/features/agenda/AgendaPage.test.tsx -t "kind=google"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/agenda/AgendaPage.tsx apps/web/src/features/agenda/AgendaPage.test.tsx
git commit -m "feat: evento kind=google ganha cor neutra própria na Agenda"
```

---

### Task 8: frontend — vincular a um cliente do CRM (o gap achado no grounding)

O design spec assumia que o modal de detalhe do evento já tinha um seletor de cliente — **não
tem**. `EventDetailModal` hoje não oferece nenhuma forma de ligar/trocar `client_id` depois da
criação, para nenhum `kind`. Esta task constrói o mínimo necessário: um controle inline, visível
para qualquer evento que não seja cobrança (que já mostra o cliente por outro caminho).

**Files:**
- Modify: `apps/web/src/features/agenda/AgendaPage.tsx`
- Test: `apps/web/src/features/agenda/AgendaPage.test.tsx`

**Interfaces:**
- Consumes: `GET /crm/clients?search=&limit=` (existing endpoint), `PATCH /agenda/events/{id}` with `{ client_id }` (existing endpoint, already accepts this field).
- Produces: a `ClienteVinculo` component, local to `AgendaPage.tsx`.

- [ ] **Step 1: Write the failing test**

Add to `apps/web/src/features/agenda/AgendaPage.test.tsx`, in its **own** `describe` block with the
clock congelado (`vi.setSystemTime`) — the fixture event is dated 2026-09-12, and `AgendaPage`
anchors the calendar on "hoje"; without freezing the clock, this test would only pass while the
real date happens to fall in September 2026 (a time-bomb test, the exact class this repo's
CLAUDE.md §5.2 warns against repeatedly). Restore in `afterEach`, never in the test body — a failed
assertion before an inline restore would leak fake timers into the next test:

```typescript
describe("AgendaPage — vínculo de cliente no detalhe do evento", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("EventDetailModal: vincula o evento a um cliente do CRM (evento sem client_id)", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-12T12:00:00.000Z"));
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const event = {
      id: "ev-google-2",
      tenant_id: "t1",
      title: "Visita",
      description: "",
      kind: "google",
      status: "scheduled",
      priority: "normal",
      source: "google",
      starts_at: "2026-09-12T16:00:00.000Z",
      ends_at: "2026-09-12T17:00:00.000Z",
      all_day: false,
      location: "",
      meeting_url: null,
      guests: [],
      amount_cents: null,
      external_ref: null,
      google_event_id: "gcal-2",
      client_id: null,
      client_name: null,
      created_by_ai: false,
      created_at: "2026-09-12T00:00:00.000Z",
    };
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/agenda/events") return Promise.resolve({ data: [event] } as never);
      if (url === "/crm/clients") {
        return Promise.resolve({ data: [{ id: "c1", name: "Maria Cliente" }] } as never);
      }
      return Promise.resolve({ data: [] } as never);
    });
    vi.mocked(api.patch).mockResolvedValue({
      data: { ...event, client_id: "c1", client_name: "Maria Cliente" },
    } as never);

    renderPage();
    await user.click(await screen.findByTestId("chip-evento-ev-google-2"));
    await user.click(await screen.findByRole("button", { name: "Vincular a um cliente" }));
    await user.type(screen.getByPlaceholderText("Buscar cliente..."), "Maria");
    await user.click(screen.getByRole("button", { name: "Buscar" }));
    await user.click(await screen.findByRole("button", { name: "Maria Cliente" }));

    expect(vi.mocked(api.patch)).toHaveBeenCalledWith("/agenda/events/ev-google-2", {
      client_id: "c1",
    });
    expect(await screen.findByText(/Cliente:/)).toHaveTextContent("Maria Cliente");
  });
});
```

`afterEach` needs importing at the top of the test file (the file's current import line is `import
{ beforeEach, describe, expect, it, vi } from "vitest";` — add `afterEach` to it).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && pnpm vitest run src/features/agenda/AgendaPage.test.tsx -t "vincula o evento"`
Expected: FAIL — no "Vincular a um cliente" button exists yet.

- [ ] **Step 3: Write the implementation**

In `apps/web/src/features/agenda/AgendaPage.tsx`, add the import for `Client` type at the top (alongside the existing `AgendaEvent, Charge, Notification, Payable` import):

```typescript
import type { AgendaEvent, Charge, Client, Notification, Payable } from "@e1p/shared-types";
```

Add the `ClienteVinculo` component right after `EventDetailModal`'s closing brace (or above it — either is fine, matching the file's existing ordering of helper components after the main export):

```typescript
function ClienteVinculo({
  eventId,
  clientId,
  clientName,
  onLinked,
}: {
  eventId: string;
  clientId: string | null;
  clientName: string | null;
  onLinked: (clientId: string, clientName: string) => void;
}) {
  const [showSearch, setShowSearch] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Client[]>([]);
  const [busy, setBusy] = useState(false);

  async function search() {
    if (!query.trim()) return;
    const { data } = await api.get<Client[]>("/crm/clients", {
      params: { search: query, limit: 10 },
    });
    setResults(Array.isArray(data) ? data : []);
  }

  async function link(client: Client) {
    setBusy(true);
    try {
      await api.patch(`/agenda/events/${eventId}`, { client_id: client.id });
      onLinked(client.id, client.name);
      setShowSearch(false);
    } finally {
      setBusy(false);
    }
  }

  if (clientId && !showSearch) {
    return (
      <p className="flex items-center justify-between text-neutral-600">
        <span>
          Cliente: <strong>{clientName ?? "vinculado"}</strong>
        </span>
        <button onClick={() => setShowSearch(true)} className="text-xs text-primary-600 hover:underline">
          Trocar
        </button>
      </p>
    );
  }

  if (!showSearch) {
    return (
      <button onClick={() => setShowSearch(true)} className="text-xs text-primary-600 hover:underline">
        Vincular a um cliente
      </button>
    );
  }

  return (
    <div className="space-y-1.5">
      <div className="flex gap-1.5">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && search()}
          placeholder="Buscar cliente..."
          className="min-w-0 flex-1 rounded-lg border border-neutral-200 px-2 py-1 text-xs outline-none focus:border-primary-400"
        />
        <button onClick={search} className="rounded-lg bg-neutral-100 px-2 py-1 text-xs">
          Buscar
        </button>
      </div>
      {results.length > 0 && (
        <ul className="space-y-1">
          {results.map((c) => (
            <li key={c.id}>
              <button
                onClick={() => link(c)}
                disabled={busy}
                className="w-full rounded-lg bg-neutral-50 px-2 py-1 text-left text-xs hover:bg-neutral-100 disabled:opacity-60"
              >
                {c.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

In `EventDetailModal`, add local state for the client (right after the existing `const [busy, setBusy] = useState(false);` line):

```typescript
  const [clientId, setClientId] = useState(event.client_id);
  const [clientName, setClientName] = useState(event.client_name);
```

And render the control — insert it right after the `{event.description && ...}` block and before `{isPagar && payable && (...)}`, so it's visible for every kind but doesn't compete visually with the charge/payable-specific sections:

```typescript
        {!isPagar && !isReceber && (
          <ClienteVinculo
            eventId={event.id}
            clientId={clientId}
            clientName={clientName}
            onLinked={(id, name) => {
              setClientId(id);
              setClientName(name);
            }}
          />
        )}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/web && pnpm vitest run src/features/agenda/AgendaPage.test.tsx -t "vincula o evento"`
Expected: PASS

- [ ] **Step 5: Run the full frontend test file + typecheck**

Run: `cd apps/web && pnpm vitest run src/features/agenda/AgendaPage.test.tsx && pnpm typecheck`
Expected: all green, no TS errors.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/features/agenda/AgendaPage.tsx apps/web/src/features/agenda/AgendaPage.test.tsx
git commit -m "feat: EventDetailModal ganha controle para vincular o evento a um cliente do CRM"
```

---

### Task 9: aceite em ~360px do novo controle (régua do repo)

Este repositório proíbe declarar uma tela "pronta" sem medir em 360px (CLAUDE.md §5.1: "layout só
se prova medindo", nunca por classe CSS). O `EventDetailModal` já é medido pela régua existente
(`agenda-evento-360` em `apps/web/e2e/`) — esta task confirma que o controle novo não regride
aquela medição, e não precisa de spec/case novo se a régua já cobre o modal por inteiro.

**Files:**
- Modify: nenhum arquivo de produção (só verificação)
- Verify: `apps/web/e2e/agenda-evento-360.spec.ts` (existing)

**Interfaces:**
- Consumes: nothing new.

- [ ] **Step 1: Rode a régua de 360px existente para o modal de evento**

Run: `cd apps/web && pnpm e2e --grep "agenda-evento-360"`

(Se o nome do spec/grep não bater, ajuste para o padrão real do arquivo — confira
`apps/web/e2e/agenda-evento-360.spec.ts` para o `test.describe`/`test` exato antes de rodar.)

Expected: PASS. Se falhar, o novo controle (`ClienteVinculo`) provavelmente introduziu um alvo
abaixo de 44px de altura ou texto vazando a borda do modal — ajuste com `min-h-[44px]` nos
botões e `break-words`/`min-w-0` no texto do nome do cliente, seguindo o padrão já estabelecido
no resto do arquivo (ver o comentário de `Modal` sobre `testId` na caixa, §5.1 do CLAUDE.md).

- [ ] **Step 2: Se precisar de ajuste, repita o teste até verde, depois commit**

```bash
git add apps/web/src/features/agenda/AgendaPage.tsx
git commit -m "fix: ajusta o controle de vínculo de cliente para caber em 360px"
```

(Pule este commit se o Step 1 já passou sem alteração nenhuma.)

---

### Task 10: atualiza o CLAUDE.md (obrigatório, mesmo peso do teste — §5 do repo)

**Files:**
- Modify: `f:\Projetos\e1p\escritorio-1-pessoa\CLAUDE.md`

**Interfaces:**
- Consumes: nothing.

- [ ] **Step 1: Substitua a linha do roadmap**

Em `CLAUDE.md`, seção "6. Estado atual / roadmap", troque a linha:

```
- [ ] **Integração Google (Meet/Calendar)** — PENDENTE: gerar Meet automaticamente exige OAuth Google (Google Cloud project + Calendar API). Hoje: campo manual + botão que abre meet.google.com/new. É o módulo 6 (API Hub) da spec — fazer quando o usuário fornecer credenciais Google.
```

por:

```
- [x] **Integração Google (Meet/Calendar)** — bidirecional em produção desde 26/08/2026. e1p → Google: criar/remarcar/cancelar reunião/atendimento/audiência/bloqueio no e1p gera o espelho no Google Calendar (com Meet automático para os três primeiros), desde a Story 4.1 (11/07) — o "PENDENTE" desta linha e a dívida "reschedule/cancel não sincronizam" (Story 4.1) estavam DESATUALIZADOS: o hardening pós-4.1 já cobria os dois. Google → e1p: `google_calendar/sync.py` puxa incremental (`syncToken`) a cada sweep do worker, criando/atualizando/cancelando `AgendaEvent(kind="google")` — sem eco de volta. Vincular a um cliente do CRM é manual, no detalhe do evento (`ClienteVinculo`, `PATCH /agenda/events/{id}`). Ver `docs/superpowers/specs/2026-08-26-google-calendar-sync-bidirecional-design.md`.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md — integração Google deixa de ser PENDENTE, sync bidirecional em produção"
```

---

### Task 11: gates finais

**Files:** nenhum (só verificação)

- [ ] **Step 1: rode o backend inteiro**

Run: `cd apps/api && python -m pytest -q`
Expected: todos verdes, incluindo os novos testes das Tasks 1-5 (sem `rls_e2e`, que já rodou na Task 6).

- [ ] **Step 2: rode `ruff`**

Run: `cd apps/api && ruff check .`
Expected: `All checks passed`.

- [ ] **Step 3: rode o frontend inteiro**

Run: `cd apps/web && pnpm typecheck && pnpm lint && pnpm vitest run`
Expected: todos verdes.

- [ ] **Step 4: rode a régua de 360px completa (não só o spec do evento)**

Run: `cd apps/web && pnpm e2e`
Expected: todos verdes — nenhuma outra tela foi tocada, mas o `AgendaPage.tsx` mudou e vale
confirmar que a régua inteira (não só `agenda-evento-360`) continua passando.

- [ ] **Step 5: valide manualmente em produção, com uma conta Google real conectada**

(Não automatizável — mesma categoria de validação que a Story 4.1 já registrou para o OAuth
ponta-a-ponta.) Criar um evento direto no Google Calendar do celular, aguardar até 1 minuto,
confirmar que aparece na Agenda do e1p com `kind="google"`; cancelar no e1p, confirmar que some
do Google; cancelar no Google, confirmar que aparece cancelado no e1p. Registrar o resultado
(inclusive se algo divergir) como Completion Note ao fechar esta entrega — mesma disciplina do
resto do repositório (CLAUDE.md §5, passo 4).
