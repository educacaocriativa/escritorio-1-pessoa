"""Testes do sync Google Calendar -> e1p (pull). Todas as chamadas HTTP são MOCKADAS.

O índice único de `google_event_id` (migration 0081) é validado à parte, contra Postgres real,
em test_google_calendar_sync_rls.py — a suíte SQLite deste arquivo não o exercita (o fixture
`db` cria as tabelas via `Base.metadata.create_all`, que não aplica índice criado só via
`op.create_index` na migration).
"""
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.agenda.models import STATUS_CANCELLED, AgendaEvent
from app.modules.google_calendar import sync
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


# ── Incidente de produção (2026-08-27): google_event_id > 128 chars ──────────
#
# Confirmado em produção: eventos importados de calendários externos (Outlook/Exchange via
# interop do Google Workspace) têm `id` de até 181 caracteres — bem além dos 26 chars do
# formato próprio do Google. `google_event_id` era `String(128)`: o INSERT falhava com
# `StringDataRightTruncation`, a transação inteira dava rollback, e NENHUM evento daquele
# tenant sincronizava (não só o comprido — o `pull_changes` processa o lote inteiro numa
# única transação). Google documenta até 1024 chars para `id` de evento.
def test_google_event_id_column_accepts_external_calendar_ids():
    """Regressão rápida (sem Postgres): a coluna precisa ser larga o bastante para IDs
    importados de calendários externos. SQLite não aplica limite de VARCHAR (por isso este
    teste confere o TAMANHO DECLARADO da coluna, não insere e deixa passar por acidente) —
    a prova de que o banco REAL aceita mora em test_google_calendar_sync_rls.py."""
    column = AgendaEvent.__table__.c.google_event_id
    assert column.type.length is not None and column.type.length >= 1024
