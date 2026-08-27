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
