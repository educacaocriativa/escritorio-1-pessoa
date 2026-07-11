"""Testes do backfill de Anexos para o S3 (Story 3.5, Task 5).

Roda o script contra o SQLite de teste com `get_db`/`tenant_session` sobrescritos (mesmo padrão
de conftest.py::_override_factory) e o storage mockado (dict). Valida a migração correta
(storage_key preenchido, data zerado) e a idempotência (segunda rodada não reprocessa).
"""
from contextlib import contextmanager

import pytest
from sqlalchemy.orm import Session

from app.core import storage
from app.scripts import migrate_attachments_to_s3 as backfill

TENANT_ID = "11111111-2222-3333-4444-555555555555"


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def is_configured(self) -> bool:
        return True

    def put_object(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data


@pytest.fixture()
def seeded(db: Session):
    from app.modules.attachments.models import Attachment
    from app.modules.auth.models import Tenant

    db.add(Tenant(id=TENANT_ID, slug="bkf", legal_name="Backfill SA", document="123"))
    for i in range(3):
        db.add(Attachment(
            tenant_id=TENANT_ID, owner_type="payable", owner_id=f"p{i}", label="boleto",
            filename=f"doc{i}.pdf", content_type="application/pdf", size=5,
            data=f"bytes{i}".encode(), storage_key=None,
        ))
    db.commit()
    return db


@pytest.fixture()
def wired(monkeypatch: pytest.MonkeyPatch, seeded: Session) -> FakeStorage:
    fake = FakeStorage()
    monkeypatch.setattr(storage, "is_configured", fake.is_configured)
    monkeypatch.setattr(storage, "put_object", fake.put_object)

    def _get_db():
        yield seeded

    @contextmanager
    def _tenant_session(_tid: str):
        yield seeded

    monkeypatch.setattr(backfill, "get_db", _get_db)
    monkeypatch.setattr(backfill, "tenant_session", _tenant_session)
    return fake


def test_backfill_migrates_legacy_rows(wired: FakeStorage, seeded: Session):
    from app.modules.attachments.models import Attachment

    rc = backfill.main()
    assert rc == 0
    rows = seeded.query(Attachment).all()
    assert len(rows) == 3
    for r in rows:
        assert r.data is None
        assert r.storage_key is not None
        assert r.storage_key in wired.objects


def test_backfill_is_idempotent(wired: FakeStorage, seeded: Session):
    assert backfill.main() == 0
    migrated_first = len(wired.objects)
    assert migrated_first == 3
    # Segunda rodada: nada pendente (storage_key já setado) → não reprocessa.
    n = backfill.migrate_tenant(TENANT_ID)
    assert n == 0


def test_backfill_aborts_without_bucket(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(storage, "is_configured", lambda: False)
    assert backfill.main() == 1
