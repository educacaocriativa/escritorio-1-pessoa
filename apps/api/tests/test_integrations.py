"""Testes do módulo de Integrações: CRUD de chaves + captura pública de lead (API externa)."""
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import events
from app.modules.funnels import automation

REGISTER = {
    "legal_name": "Integra SA",
    "document": "61616161000107",
    "slug": "integrasa",
    "email": "integra@example.com",
    "name": "In",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_create_key_shows_raw_key_once(client: TestClient, headers):
    resp = client.post("/integrations/leads/keys", json={"label": "Site Dóro"}, headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["raw_key"]
    assert body["key_prefix"] == body["raw_key"][:8]

    listed = client.get("/integrations/leads/keys", headers=headers).json()
    assert listed[0]["label"] == "Site Dóro"
    assert "raw_key" not in listed[0]  # a chave crua nunca reaparece


def test_public_capture_creates_lead_with_source_api(client: TestClient, headers):
    key = client.post(
        "/integrations/leads/keys", json={"label": "Site X"}, headers=headers
    ).json()
    resp = client.post(
        f"/public/leads/{key['raw_key']}",
        json={
            "name": "Lead Externo",
            "email": "lead@example.com",
            "notes": "Prefere data em dezembro",
            "fields": {"ocasiao": "aniversário"},
        },
    )
    assert resp.status_code == 200
    clients = client.get("/crm/clients", headers=headers).json()
    lead = next(c for c in clients if c["name"] == "Lead Externo")
    assert lead["source"] == "api"
    assert "Prefere data em dezembro" in lead["notes"]
    assert "ocasiao: aniversário" in lead["notes"]


def test_public_capture_rejects_unknown_key(client: TestClient):
    resp = client.post("/public/leads/chave-invalida", json={"name": "X"})
    assert resp.status_code == 401


def test_public_capture_rejects_revoked_key(client: TestClient, headers):
    key = client.post(
        "/integrations/leads/keys", json={"label": "Revogada"}, headers=headers
    ).json()
    client.post(f"/integrations/leads/keys/{key['id']}/revoke", headers=headers)
    resp = client.post(f"/public/leads/{key['raw_key']}", json={"name": "X"})
    assert resp.status_code == 401


def test_rate_limit_blocks_after_threshold(client: TestClient, headers):
    key = client.post(
        "/integrations/leads/keys", json={"label": "Rate"}, headers=headers
    ).json()
    for _ in range(30):
        ok = client.post(f"/public/leads/{key['raw_key']}", json={"name": "X"})
        assert ok.status_code == 200
    blocked = client.post(f"/public/leads/{key['raw_key']}", json={"name": "X"})
    assert blocked.status_code == 429


def test_requires_auth_for_key_management(client: TestClient):
    assert client.get("/integrations/leads/keys").status_code == 401


def test_public_capture_triggers_auto_enroll(client: TestClient, headers, db: Session, monkeypatch):
    # A fixture `client` roda events.clear() no setup — religa o assinante manualmente pra
    # provar a integração ponta a ponta (mesmo padrão de test_crm.py::test_move_emits_event).
    # O assinante abre sua PRÓPRIA tenant_session (Postgres real) — nos testes (SQLite),
    # aponta pra sessão compartilhada do fixture `db`, mesmo padrão de test_notifications.py.
    @contextmanager
    def _fake_tenant_session(_tenant_id):
        yield db

    monkeypatch.setattr(automation, "tenant_session", _fake_tenant_session)
    automation.register()
    try:
        funnel = client.post(
            "/funnels", json={"name": "Entrada", "nodes": [{"id": "n1"}]}, headers=headers
        ).json()
        client.patch(
            "/settings/profile",
            json={"default_entry_funnel_id": funnel["id"]},
            headers=headers,
        )
        key = client.post(
            "/integrations/leads/keys", json={"label": "Auto"}, headers=headers
        ).json()
        client.post(f"/public/leads/{key['raw_key']}", json={"name": "Lead Auto"})

        lead = next(
            c for c in client.get("/crm/clients", headers=headers).json()
            if c["name"] == "Lead Auto"
        )
        runs = client.get(f"/funnels/{funnel['id']}/runs", headers=headers).json()
        assert any(r["client_id"] == lead["id"] for r in runs)
    finally:
        events.clear()
