"""Endurecimento da integração Google (dívida da Story 4.1 endereçada antes de produção):

1. Tokens OAuth (`access_token`/`refresh_token`) CIFRADOS EM REPOUSO — nunca texto plano no banco.
2. reschedule/cancel de um AgendaEvent com `google_event_id` SINCRONIZAM de volta pro Google
   (best-effort/não bloqueante — falha do Google não derruba a operação local).

Todas as chamadas HTTP ao Google são MOCKADAS (não batemos na API real).
"""
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.token_crypto import _PREFIX, decrypt_token, encrypt_token
from app.modules.agenda import service as agenda
from app.modules.agenda.models import STATUS_CANCELLED, AgendaEvent
from app.modules.google_calendar.models import GoogleCredential

TENANT = "t" * 12


# ── 1. Criptografia em repouso ───────────────────────────────────────────────
def test_encrypt_decrypt_roundtrip_and_idempotent():
    ct = encrypt_token("1//super-secret-refresh")
    assert ct.startswith(_PREFIX)
    assert "super-secret-refresh" not in ct  # o segredo não vaza no ciphertext
    assert decrypt_token(ct) == "1//super-secret-refresh"
    # Idempotente: não re-cifra um valor já cifrado (evita camadas duplas).
    assert encrypt_token(ct) == ct
    # Vazio/None passam direto (colunas com default "").
    assert encrypt_token("") == ""
    assert decrypt_token("") == ""
    assert encrypt_token(None) is None


def test_decrypt_of_legacy_plaintext_passes_through():
    # Best-effort: token gravado ANTES da criptografia (sem o prefixo) é lido como está,
    # sem quebrar. Ao ser regravado pelo código, passa a ser cifrado.
    assert decrypt_token("legacy-plaintext-token") == "legacy-plaintext-token"


def test_tokens_encrypted_at_rest_in_db(db: Session):
    """A coluna crua NUNCA contém o texto plano; a leitura via ORM decifra transparente."""
    cred = GoogleCredential(
        tenant_id=TENANT,
        google_account_email="owner@gmail.com",
        access_token="ya29.super-secret-access",
        refresh_token="1//super-secret-refresh",
    )
    db.add(cred)
    db.commit()

    # Leitura CRUA (sem o TypeDecorator): o banco guarda ciphertext, não o segredo.
    raw = db.execute(
        text("SELECT access_token, refresh_token FROM google_credentials WHERE id = :id"),
        {"id": cred.id},
    ).one()
    assert raw[0].startswith(_PREFIX)
    assert raw[1].startswith(_PREFIX)
    assert "super-secret-access" not in raw[0]
    assert "super-secret-refresh" not in raw[1]

    # Leitura via ORM: decifra de volta ao texto plano (transparente para o código).
    db.expire_all()
    fresh = db.get(GoogleCredential, cred.id)
    assert fresh.access_token == "ya29.super-secret-access"
    assert fresh.refresh_token == "1//super-secret-refresh"


def test_legacy_plaintext_row_still_readable_via_orm(db: Session):
    """Credencial gravada antes da criptografia (texto plano cru no banco) segue legível."""
    cred = GoogleCredential(tenant_id=TENANT, access_token="x", refresh_token="x")
    db.add(cred)
    db.commit()
    # Sobrescreve com texto plano CRU (simula dado pré-criptografia).
    db.execute(
        text("UPDATE google_credentials SET refresh_token = 'legacy-refresh' WHERE id = :id"),
        {"id": cred.id},
    )
    db.commit()
    db.expire_all()
    assert db.get(GoogleCredential, cred.id).refresh_token == "legacy-refresh"


# ── 2. Sync de reschedule/cancel de volta pro Google ─────────────────────────
def _connect_google(db: Session) -> None:
    """Cria uma credencial Google conectada com token válido (não expira → sem refresh)."""
    db.add(
        GoogleCredential(
            tenant_id=TENANT,
            google_account_email="owner@gmail.com",
            access_token="valid-access-token",
            refresh_token="valid-refresh-token",
            token_expiry=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    db.commit()


def _make_event(db: Session, *, google_event_id: str | None) -> AgendaEvent:
    ev = AgendaEvent(
        tenant_id=TENANT,
        title="Reunião com cliente",
        kind="reuniao",
        starts_at=datetime(2026, 7, 20, 14, 0, tzinfo=UTC),
        ends_at=datetime(2026, 7, 20, 15, 0, tzinfo=UTC),
        google_event_id=google_event_id,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


class _FakeResp:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None


def test_reschedule_patches_google_when_event_linked(db: Session, monkeypatch):
    _connect_google(db)
    ev = _make_event(db, google_event_id="gcal-evt-123")
    calls: list[dict] = []

    def fake_patch(url: str, **kw):
        calls.append({"url": url, "json": kw.get("json")})
        return _FakeResp(200)

    monkeypatch.setattr(httpx, "patch", fake_patch)

    new_start = datetime(2026, 7, 21, 16, 0, tzinfo=UTC)
    new_end = datetime(2026, 7, 21, 17, 0, tzinfo=UTC)
    event, _ = agenda.reschedule_event(
        db, event_id=ev.id, tenant_id=TENANT, actor="user-1",
        starts_at=new_start, ends_at=new_end,
    )

    # O Google foi chamado no evento certo, com os novos horários.
    assert len(calls) == 1
    assert "gcal-evt-123" in calls[0]["url"]
    assert calls[0]["json"]["start"]["dateTime"].startswith("2026-07-21T16:00")
    # E a mudança local persistiu (SQLite descarta tzinfo no refresh — comparamos os campos).
    assert (event.starts_at.day, event.starts_at.hour) == (21, 16)


def test_cancel_deletes_google_when_event_linked(db: Session, monkeypatch):
    _connect_google(db)
    ev = _make_event(db, google_event_id="gcal-evt-456")
    calls: list[str] = []

    def fake_delete(url: str, **kw):
        calls.append(url)
        return _FakeResp(204)

    monkeypatch.setattr(httpx, "delete", fake_delete)

    event = agenda.cancel_event(db, event_id=ev.id, tenant_id=TENANT, actor="user-1")

    assert len(calls) == 1
    assert "gcal-evt-456" in calls[0]
    assert event.status == STATUS_CANCELLED


def test_reschedule_does_not_call_google_without_event_id(db: Session, monkeypatch):
    _connect_google(db)
    ev = _make_event(db, google_event_id=None)  # evento sem Meet vinculado
    called = {"patch": False}

    def fake_patch(url: str, **kw):
        called["patch"] = True
        return _FakeResp(200)

    monkeypatch.setattr(httpx, "patch", fake_patch)
    agenda.reschedule_event(
        db, event_id=ev.id, tenant_id=TENANT, actor="user-1",
        starts_at=datetime(2026, 7, 21, 16, 0, tzinfo=UTC),
        ends_at=datetime(2026, 7, 21, 17, 0, tzinfo=UTC),
    )
    assert called["patch"] is False


def test_google_failure_does_not_break_local_reschedule(db: Session, monkeypatch):
    """Robustez (IV1/IV2): token revogado / rede / 404 no Google NÃO derruba o reschedule local."""
    _connect_google(db)
    ev = _make_event(db, google_event_id="gcal-evt-789")

    def fake_patch(url: str, **kw):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "patch", fake_patch)

    new_start = datetime(2026, 7, 22, 9, 0, tzinfo=UTC)
    new_end = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    event, _ = agenda.reschedule_event(
        db, event_id=ev.id, tenant_id=TENANT, actor="user-1",
        starts_at=new_start, ends_at=new_end,
    )
    # O reschedule local venceu mesmo com o Google falhando (SQLite descarta tzinfo no refresh).
    assert (event.starts_at.day, event.starts_at.hour) == (22, 9)


def test_google_failure_does_not_break_local_cancel(db: Session, monkeypatch):
    _connect_google(db)
    ev = _make_event(db, google_event_id="gcal-evt-000")

    def fake_delete(url: str, **kw):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "delete", fake_delete)

    event = agenda.cancel_event(db, event_id=ev.id, tenant_id=TENANT, actor="user-1")
    assert event.status == STATUS_CANCELLED


def test_cancel_treats_google_404_as_success(db: Session, monkeypatch):
    """Evento já removido no Google (404/410) = objetivo cumprido, não é erro."""
    _connect_google(db)
    ev = _make_event(db, google_event_id="gcal-evt-410")

    def fake_delete(url: str, **kw):
        return _FakeResp(410)

    monkeypatch.setattr(httpx, "delete", fake_delete)

    from app.modules.google_calendar import service as gcal

    db.refresh(ev)
    assert gcal.delete_meet_event(db, tenant_id=TENANT, event=ev) is True
