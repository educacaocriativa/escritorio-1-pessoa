"""Testes do módulo Agenda — foco em conflitos de horário (a 'Guardiã da Agenda')."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

REGISTER = {
    "legal_name": "Clínica Maria",
    "document": "98765432000198",
    "slug": "clinicamaria",
    "email": "maria@example.com",
    "name": "Maria",
    "password": "uma-senha-bem-forte",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _event(**over):
    base = {
        "title": "Atendimento João",
        "kind": "atendimento",
        "starts_at": "2026-07-01T10:00:00+00:00",
        "ends_at": "2026-07-01T11:00:00+00:00",
    }
    return {**base, **over}


def test_create_event(client: TestClient, headers):
    resp = client.post("/agenda/events", json=_event(), headers=headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["event"]["title"] == "Atendimento João"
    assert body["event"]["status"] == "scheduled"
    assert body["conflicts"] == []


def test_create_event_with_details(client: TestClient, headers):
    resp = client.post(
        "/agenda/events",
        json=_event(
            location="Escritório centro",
            meeting_url="https://meet.google.com/abc-defg-hij",
            guests=["cliente@example.com", "cliente@example.com", " "],
        ),
        headers=headers,
    )
    assert resp.status_code == 201
    ev = resp.json()["event"]
    assert ev["location"] == "Escritório centro"
    assert ev["meeting_url"].startswith("https://meet.google.com/")
    assert ev["guests"] == ["cliente@example.com"]  # dedup + sem vazias


def test_update_event_location_and_meet(client: TestClient, headers):
    created = client.post("/agenda/events", json=_event(), headers=headers).json()["event"]
    resp = client.patch(
        f"/agenda/events/{created['id']}",
        json={"location": "Online", "meeting_url": "https://meet.google.com/xyz"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["location"] == "Online"
    assert resp.json()["meeting_url"] == "https://meet.google.com/xyz"


def test_create_requires_auth(client: TestClient):
    resp = client.post("/agenda/events", json=_event())
    assert resp.status_code == 401


def test_invalid_kind_rejected(client: TestClient, headers):
    resp = client.post("/agenda/events", json=_event(kind="festa"), headers=headers)
    assert resp.status_code == 422


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


def test_end_before_start_rejected(client: TestClient, headers):
    resp = client.post(
        "/agenda/events",
        json=_event(starts_at="2026-07-01T11:00:00+00:00", ends_at="2026-07-01T10:00:00+00:00"),
        headers=headers,
    )
    assert resp.status_code == 422


def test_overlapping_events_conflict(client: TestClient, headers):
    client.post("/agenda/events", json=_event(), headers=headers)  # 10:00-11:00
    resp = client.post(
        "/agenda/events",
        json=_event(
            title="Reunião",
            kind="reuniao",
            starts_at="2026-07-01T10:30:00+00:00",
            ends_at="2026-07-01T11:30:00+00:00",
        ),
        headers=headers,
    )
    assert resp.status_code == 201
    conflicts = resp.json()["conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["title"] == "Atendimento João"


def test_adjacent_events_do_not_conflict(client: TestClient, headers):
    client.post("/agenda/events", json=_event(), headers=headers)  # 10:00-11:00
    resp = client.post(
        "/agenda/events",
        json=_event(
            starts_at="2026-07-01T11:00:00+00:00",  # começa quando o outro acaba
            ends_at="2026-07-01T12:00:00+00:00",
        ),
        headers=headers,
    )
    assert resp.json()["conflicts"] == []


def test_prazo_does_not_occupy_time(client: TestClient, headers):
    # Prazo é marcador, não ocupa horário — não conflita com atendimento no mesmo horário.
    client.post("/agenda/events", json=_event(), headers=headers)  # atendimento 10:00-11:00
    resp = client.post(
        "/agenda/events",
        json=_event(title="Prazo fatal", kind="prazo", priority="critical"),
        headers=headers,
    )
    assert resp.json()["conflicts"] == []


def test_cancelled_event_frees_slot(client: TestClient, headers):
    created = client.post("/agenda/events", json=_event(), headers=headers).json()["event"]
    client.post(f"/agenda/events/{created['id']}/cancel", headers=headers)
    # mesmo horário não deve mais conflitar
    resp = client.post("/agenda/events", json=_event(title="Outro"), headers=headers)
    assert resp.json()["conflicts"] == []


def test_list_events_by_window(client: TestClient, headers):
    client.post("/agenda/events", json=_event(), headers=headers)
    client.post(
        "/agenda/events",
        json=_event(starts_at="2026-08-01T10:00:00+00:00", ends_at="2026-08-01T11:00:00+00:00"),
        headers=headers,
    )
    resp = client.get(
        "/agenda/events",
        params={"start": "2026-07-01T00:00:00+00:00", "end": "2026-07-31T23:59:59+00:00"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 1  # só o de julho


def test_get_missing_event_404(client: TestClient, headers):
    resp = client.get("/agenda/events/inexistente", headers=headers)
    assert resp.status_code == 404


def test_update_event(client: TestClient, headers):
    created = client.post("/agenda/events", json=_event(), headers=headers).json()["event"]
    resp = client.patch(
        f"/agenda/events/{created['id']}",
        json={"status": "confirmed", "title": "Atendimento confirmado"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"
    assert resp.json()["title"] == "Atendimento confirmado"


def test_update_rejects_invalid_status(client: TestClient, headers):
    created = client.post("/agenda/events", json=_event(), headers=headers).json()["event"]
    resp = client.patch(
        f"/agenda/events/{created['id']}", json={"status": "banana"}, headers=headers
    )
    assert resp.status_code == 422


def test_cannot_cancel_already_cancelled(client: TestClient, headers):
    created = client.post("/agenda/events", json=_event(), headers=headers).json()["event"]
    client.post(f"/agenda/events/{created['id']}/cancel", headers=headers)
    resp = client.post(f"/agenda/events/{created['id']}/cancel", headers=headers)
    assert resp.status_code == 409


def test_cannot_reschedule_cancelled(client: TestClient, headers):
    created = client.post("/agenda/events", json=_event(), headers=headers).json()["event"]
    client.post(f"/agenda/events/{created['id']}/cancel", headers=headers)
    resp = client.post(
        f"/agenda/events/{created['id']}/reschedule",
        json={"starts_at": "2026-07-02T10:00:00+00:00", "ends_at": "2026-07-02T11:00:00+00:00"},
        headers=headers,
    )
    assert resp.status_code == 409


def test_zero_duration_rejected(client: TestClient, headers):
    resp = client.post(
        "/agenda/events",
        json=_event(starts_at="2026-07-01T10:00:00+00:00", ends_at="2026-07-01T10:00:00+00:00"),
        headers=headers,
    )
    assert resp.status_code == 422


def test_negative_amount_rejected(client: TestClient, headers):
    resp = client.post(
        "/agenda/events",
        json=_event(kind="cobranca_receber", amount_cents=-100),
        headers=headers,
    )
    assert resp.status_code == 422


def test_list_respects_limit(client: TestClient, headers):
    for h in range(9, 14):
        client.post(
            "/agenda/events",
            json=_event(starts_at=f"2026-07-01T{h:02d}:00:00+00:00",
                        ends_at=f"2026-07-01T{h:02d}:30:00+00:00"),
            headers=headers,
        )
    resp = client.get("/agenda/events", params={"limit": 2}, headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_naive_datetime_coerced(client: TestClient, headers):
    # datetime sem timezone é aceito (assumido UTC) e o conflito ainda funciona
    client.post("/agenda/events", json=_event(), headers=headers)  # aware 10-11 UTC
    resp = client.post(
        "/agenda/events",
        json=_event(
            kind="reuniao",
            starts_at="2026-07-01T10:30:00",  # naive
            ends_at="2026-07-01T11:30:00",
        ),
        headers=headers,
    )
    assert resp.status_code == 201
    assert len(resp.json()["conflicts"]) == 1


def test_reschedule_detects_conflict(client: TestClient, headers):
    a = client.post("/agenda/events", json=_event(), headers=headers).json()["event"]  # 10-11
    client.post(
        "/agenda/events",
        json=_event(
            title="Reunião tarde",
            kind="reuniao",
            starts_at="2026-07-01T15:00:00+00:00",
            ends_at="2026-07-01T16:00:00+00:00",
        ),
        headers=headers,
    )
    # remarca o atendimento para cima da reunião
    resp = client.post(
        f"/agenda/events/{a['id']}/reschedule",
        json={"starts_at": "2026-07-01T15:30:00+00:00", "ends_at": "2026-07-01T16:30:00+00:00"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert len(resp.json()["conflicts"]) == 1
    assert resp.json()["event"]["starts_at"].startswith("2026-07-01T15:30")


# ── Geração automática de Meet via Google (Story 4.1) ────────────────────────
def test_meet_not_generated_without_google(client: TestClient, headers):
    """Sem Google conectado, evento de reunião sai sem meeting_url (IV1/AC3 — hoje preservado)."""
    resp = client.post("/agenda/events", json=_event(kind="reuniao"), headers=headers)
    assert resp.status_code == 201
    ev = resp.json()["event"]
    assert ev["meeting_url"] is None
    assert ev["google_event_id"] is None


def test_meet_generated_when_google_connected(
    client: TestClient, headers, monkeypatch, db: Session
):
    """Caminho feliz: com id de verdade, os TRÊS campos do espelho são carimbados juntos.

    O `google_account_email` é lido do banco porque não está em `EventOut` (é metadado de
    procedência, não dado de tela) — e sem esta asserção nada distinguiria a guarda da #306
    de uma guarda que engole o carimbo de conta.
    """
    from app.modules.agenda.models import AgendaEvent
    from app.modules.google_calendar import service as gcal

    monkeypatch.setattr(
        gcal, "create_meet_event",
        lambda *a, **k: ("https://meet.google.com/abc-defg-hij", "gcal-evt-1", "dono@gmail.com"),
    )
    resp = client.post("/agenda/events", json=_event(kind="reuniao"), headers=headers)
    assert resp.status_code == 201
    ev = resp.json()["event"]
    assert ev["meeting_url"] == "https://meet.google.com/abc-defg-hij"
    assert ev["google_event_id"] == "gcal-evt-1"
    assert db.get(AgendaEvent, ev["id"]).google_account_email == "dono@gmail.com"


def test_google_200_sem_id_nao_grava_meio_espelho(
    client: TestClient, headers, monkeypatch, db: Session, caplog
):
    """200 do Google com `hangoutLink` e SEM `id`: nenhum dos três campos é carimbado (#306).

    O estado que esta guarda impede é "link de Meet sem espelho rastreável": `patch_meet_event`
    e `delete_meet_event` sairiam em `if not event.google_event_id`, o pull de `sync.py`
    duplicaria o evento, e o link escaparia para sempre da invalidação por troca de conta
    (`_invalidar_vinculos_de_outra_conta` filtra por `google_event_id IS NOT NULL`).

    O link vai junto de propósito: neste ramo não existe link digitado pelo usuário (ele só
    roda quando `not data.meeting_url`), então descartar não destrói trabalho de ninguém.
    """
    import logging

    from app.modules.agenda.models import AgendaEvent
    from app.modules.google_calendar import service as gcal

    monkeypatch.setattr(
        gcal, "create_meet_event",
        lambda *a, **k: ("https://meet.google.com/orf-anho-xyz", None, "dono@gmail.com"),
    )
    with caplog.at_level(logging.WARNING, logger="app.modules.agenda.service"):
        resp = client.post("/agenda/events", json=_event(kind="reuniao"), headers=headers)

    assert resp.status_code == 201, resp.text  # a criação local NUNCA cai por causa do Google
    ev = resp.json()["event"]
    assert ev["meeting_url"] is None, "link de Meet sem id é órfão: não pode ser gravado"
    assert ev["google_event_id"] is None
    linha = db.get(AgendaEvent, ev["id"])
    assert linha.google_account_email is None, (
        "carimbar a conta sem id deixa a linha fora do WHERE da invalidação do #305"
    )
    assert "[google:create_meet:sem_id]" in caplog.text


def test_google_200_com_id_vazio_e_recusado_como_ausente(
    client: TestClient, headers, monkeypatch, db: Session
):
    """`id == ""` é recusado igual a `None` — a guarda é falsy, não `is not None`.

    String vazia não endereça evento nenhum no Google E é `NOT NULL` para o índice único
    parcial `ix_agenda_events_tenant_google_event_id` (migration 0081): dois eventos assim
    estourariam unicidade. Mesma escolha de `sync.py::_apply_item` (`if not google_event_id`).
    """
    from app.modules.agenda.models import AgendaEvent
    from app.modules.google_calendar import service as gcal

    monkeypatch.setattr(
        gcal, "create_meet_event",
        lambda *a, **k: ("https://meet.google.com/vaz-io-xyz", "", "dono@gmail.com"),
    )
    resp = client.post("/agenda/events", json=_event(kind="reuniao"), headers=headers)
    assert resp.status_code == 201, resp.text
    ev = resp.json()["event"]
    assert ev["meeting_url"] is None
    assert not ev["google_event_id"]
    assert db.get(AgendaEvent, ev["id"]).google_account_email is None


def test_manual_meeting_url_preserved_google_not_called(client: TestClient, headers, monkeypatch):
    from app.modules.google_calendar import service as gcal

    calls = {"n": 0}

    def _spy(*a, **k):
        calls["n"] += 1
        return ("https://meet.google.com/should-not-win", "x", "dono@gmail.com")

    monkeypatch.setattr(gcal, "create_meet_event", _spy)
    resp = client.post(
        "/agenda/events",
        json=_event(kind="reuniao", meeting_url="https://zoom.us/j/12345"),
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["event"]["meeting_url"] == "https://zoom.us/j/12345"
    assert calls["n"] == 0  # link manual (Zoom) tem prioridade — Google nem é chamado


def test_meet_failure_does_not_break_event(client: TestClient, headers, monkeypatch):
    """Falha na integração (create_meet_event retorna None) NÃO derruba a criação (IV1)."""
    from app.modules.google_calendar import service as gcal

    monkeypatch.setattr(gcal, "create_meet_event", lambda *a, **k: None)
    resp = client.post("/agenda/events", json=_event(kind="reuniao"), headers=headers)
    assert resp.status_code == 201
    assert resp.json()["event"]["meeting_url"] is None


def test_bloqueio_kind_is_pushed_to_google(client: TestClient, headers, monkeypatch):
    """[ATUALIZADO — Google Calendar Sync] Bloqueio de horário PASSOU a ser espelhado no
    Google (para bloquear a agenda de verdade lá também) — mas sem gerar Meet, o que é a
    invariante coberta em test_google_calendar_hardening.py::
    test_bloqueio_is_pushed_without_conference_data. Este teste garante só a fiação
    HTTP-a-HTTP: create_meet_event É chamado (nem sempre foi assim)."""
    from app.modules.google_calendar import service as gcal

    calls = {"n": 0}

    def _spy(*a, **k):
        calls["n"] += 1
        return None

    monkeypatch.setattr(gcal, "create_meet_event", _spy)
    resp = client.post("/agenda/events", json=_event(kind="bloqueio"), headers=headers)
    assert resp.status_code == 201
    assert calls["n"] == 1


def test_all_day_event_anchored_to_tenant_timezone(client: TestClient, headers):
    # Evento de dia inteiro é ancorado na meia-noite do FUSO do tenant (America/Sao_Paulo, UTC-3),
    # convertida p/ UTC: 2026-07-01 vira [2026-07-01T03:00Z, 2026-07-02T03:00Z). A data de
    # calendário (starts_at[:10]) permanece "2026-07-01" — invariante que o frontend depende (IV2).
    resp = client.post(
        "/agenda/events",
        json=_event(
            title="Vencimento",
            kind="cobranca_receber",
            all_day=True,
            starts_at="2026-07-01T00:00:00+00:00",
            ends_at="2026-07-02T00:00:00+00:00",
        ),
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    ev = resp.json()["event"]
    assert ev["all_day"] is True
    assert ev["starts_at"].startswith("2026-07-01T03:00")
    assert ev["ends_at"].startswith("2026-07-02T03:00")
    assert ev["starts_at"][:10] == "2026-07-01"  # data de calendário preservada (IV2)


def _latest_audit_is_ai(db: Session, action: str) -> bool:
    from app.core.audit import AuditEntry

    entry = db.scalars(
        select(AuditEntry)
        .where(AuditEntry.action == action)
        .order_by(AuditEntry.created_at.desc())
    ).first()
    assert entry is not None, f"nenhum AuditEntry para {action}"
    return entry.is_ai


def test_by_ai_propagated_to_audit(client: TestClient, headers, db: Session):
    # A propagação de is_ai foi fechada em update/cancel/reschedule (Story 4.5, Task 6). Como o
    # ator IA ainda não existe (CurrentUser.is_ai é sempre False), chamamos o service direto com
    # by_ai=True — provando que o rastro chega ao AuditEntry quando a camada de IA existir.
    from app.modules.agenda import service
    from app.modules.agenda.schemas import EventUpdate

    created = client.post("/agenda/events", json=_event(), headers=headers).json()["event"]
    tid = created["tenant_id"]

    service.update_event(
        db, event_id=created["id"], tenant_id=tid, actor="ai",
        data=EventUpdate(title="Reagendado pela IA"), by_ai=True,
    )
    assert _latest_audit_is_ai(db, "agenda.event.update") is True

    service.reschedule_event(
        db, event_id=created["id"], tenant_id=tid, actor="ai",
        starts_at=__import__("datetime").datetime.fromisoformat("2026-07-03T10:00:00+00:00"),
        ends_at=__import__("datetime").datetime.fromisoformat("2026-07-03T11:00:00+00:00"),
        by_ai=True,
    )
    assert _latest_audit_is_ai(db, "agenda.event.reschedule") is True

    service.cancel_event(db, event_id=created["id"], tenant_id=tid, actor="ai", by_ai=True)
    assert _latest_audit_is_ai(db, "agenda.event.cancel") is True
