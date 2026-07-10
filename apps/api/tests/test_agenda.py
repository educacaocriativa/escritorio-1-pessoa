"""Testes do módulo Agenda — foco em conflitos de horário (a 'Guardiã da Agenda')."""
import pytest
from fastapi.testclient import TestClient

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


def test_meet_generated_when_google_connected(client: TestClient, headers, monkeypatch):
    from app.modules.google_calendar import service as gcal

    monkeypatch.setattr(
        gcal, "create_meet_event",
        lambda *a, **k: ("https://meet.google.com/abc-defg-hij", "gcal-evt-1"),
    )
    resp = client.post("/agenda/events", json=_event(kind="reuniao"), headers=headers)
    assert resp.status_code == 201
    ev = resp.json()["event"]
    assert ev["meeting_url"] == "https://meet.google.com/abc-defg-hij"
    assert ev["google_event_id"] == "gcal-evt-1"


def test_manual_meeting_url_preserved_google_not_called(client: TestClient, headers, monkeypatch):
    from app.modules.google_calendar import service as gcal

    calls = {"n": 0}

    def _spy(*a, **k):
        calls["n"] += 1
        return ("https://meet.google.com/should-not-win", "x")

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


def test_bloqueio_kind_never_calls_google(client: TestClient, headers, monkeypatch):
    from app.modules.google_calendar import service as gcal

    calls = {"n": 0}

    def _spy(*a, **k):
        calls["n"] += 1
        return None

    monkeypatch.setattr(gcal, "create_meet_event", _spy)
    resp = client.post("/agenda/events", json=_event(kind="bloqueio"), headers=headers)
    assert resp.status_code == 201
    assert calls["n"] == 0  # bloqueio não gera Meet
