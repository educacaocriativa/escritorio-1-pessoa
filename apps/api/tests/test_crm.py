"""Testes do módulo CRM & Kanban."""
import pytest
from fastapi.testclient import TestClient

from app.core import events

REGISTER = {
    "legal_name": "Estúdio Ana",
    "document": "11222333000181",
    "slug": "estudioana",
    "email": "ana@example.com",
    "name": "Ana",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_board_seeds_default_stages(client: TestClient, headers):
    resp = client.get("/crm/board", headers=headers)
    assert resp.status_code == 200
    cols = resp.json()["columns"]
    names = [c["stage"]["name"] for c in cols]
    assert names == ["Entrada", "Em contato", "Proposta", "Ganho", "Perda"]
    assert cols[3]["stage"]["is_won"] is True
    assert cols[4]["stage"]["is_lost"] is True


def test_create_client_defaults_to_first_stage(client: TestClient, headers):
    resp = client.post("/crm/clients", json={"name": "João Cliente"}, headers=headers)
    assert resp.status_code == 201
    client_body = resp.json()
    stages = client.get("/crm/stages", headers=headers).json()
    assert client_body["stage_id"] == stages[0]["id"]  # Entrada


def test_create_client_requires_auth(client: TestClient):
    resp = client.post("/crm/clients", json={"name": "X"})
    assert resp.status_code == 401


def test_invalid_gender_rejected(client: TestClient, headers):
    resp = client.post(
        "/crm/clients", json={"name": "X", "gender": "alien"}, headers=headers
    )
    assert resp.status_code == 422


def test_tags_normalized(client: TestClient, headers):
    resp = client.post(
        "/crm/clients",
        json={"name": "Tagged", "tags": ["VIP", "VIP", " ", "Lead "]},
        headers=headers,
    )
    assert resp.json()["tags"] == ["VIP", "Lead"]


def test_move_client_between_stages(client: TestClient, headers):
    c = client.post("/crm/clients", json={"name": "Mover"}, headers=headers).json()
    stages = client.get("/crm/stages", headers=headers).json()
    ganho = next(s for s in stages if s["is_won"])
    resp = client.post(
        f"/crm/clients/{c['id']}/move", json={"stage_id": ganho["id"]}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["stage_id"] == ganho["id"]


def test_move_emits_event(client: TestClient, headers):
    captured = {}

    def handler(**payload):
        captured.update(payload)

    events.subscribe("crm.client.moved", handler)
    try:
        c = client.post("/crm/clients", json={"name": "Evt"}, headers=headers).json()
        stages = client.get("/crm/stages", headers=headers).json()
        ganho = next(s for s in stages if s["is_won"])
        client.post(f"/crm/clients/{c['id']}/move", json={"stage_id": ganho["id"]}, headers=headers)
    finally:
        events.clear()
    assert captured.get("is_won") is True
    assert captured.get("client_id") == c["id"]


def test_move_to_unknown_stage_404(client: TestClient, headers):
    c = client.post("/crm/clients", json={"name": "X"}, headers=headers).json()
    resp = client.post(
        f"/crm/clients/{c['id']}/move", json={"stage_id": "nao-existe"}, headers=headers
    )
    assert resp.status_code == 404


def test_segmentation_by_gender_and_tag(client: TestClient, headers):
    client.post(
        "/crm/clients",
        json={"name": "Maria", "gender": "female", "tags": ["Mãe"]},
        headers=headers,
    )
    client.post("/crm/clients", json={"name": "Pedro", "gender": "male"}, headers=headers)

    by_gender = client.get("/crm/clients", params={"gender": "female"}, headers=headers).json()
    assert [c["name"] for c in by_gender] == ["Maria"]

    by_tag = client.get("/crm/clients", params={"tag": "Mãe"}, headers=headers).json()
    assert [c["name"] for c in by_tag] == ["Maria"]


def test_search_by_name(client: TestClient, headers):
    client.post("/crm/clients", json={"name": "Carlos Eduardo"}, headers=headers)
    client.post("/crm/clients", json={"name": "Beatriz"}, headers=headers)
    resp = client.get("/crm/clients", params={"search": "carlos"}, headers=headers)
    assert [c["name"] for c in resp.json()] == ["Carlos Eduardo"]


def test_create_custom_stage(client: TestClient, headers):
    client.get("/crm/board", headers=headers)  # seed
    resp = client.post(
        "/crm/stages", json={"name": "Negociação", "is_won": False}, headers=headers
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "Negociação"


def test_stage_cannot_be_won_and_lost(client: TestClient, headers):
    resp = client.post(
        "/crm/stages", json={"name": "Bug", "is_won": True, "is_lost": True}, headers=headers
    )
    assert resp.status_code == 422


def test_delete_empty_stage_succeeds(client: TestClient, headers):
    stage = client.post("/crm/stages", json={"name": "Temporário"}, headers=headers).json()
    resp = client.delete(f"/crm/stages/{stage['id']}", headers=headers)
    assert resp.status_code == 204
    assert resp.content == b""  # 204 sem corpo


def test_delete_stage_with_clients_blocked(client: TestClient, headers):
    stages = client.get("/crm/stages", headers=headers).json()
    entrada = stages[0]
    client.post("/crm/clients", json={"name": "Fica"}, headers=headers)  # entra na Entrada
    resp = client.delete(f"/crm/stages/{entrada['id']}", headers=headers)
    assert resp.status_code == 409


def test_duplicate_stage_name_rejected(client: TestClient, headers):
    client.post("/crm/stages", json={"name": "Negociação"}, headers=headers)
    resp = client.post("/crm/stages", json={"name": "Negociação"}, headers=headers)
    assert resp.status_code == 409


def test_birthdate_future_rejected(client: TestClient, headers):
    resp = client.post(
        "/crm/clients", json={"name": "X", "birthdate": "2999-01-01"}, headers=headers
    )
    assert resp.status_code == 422


def test_too_many_tags_rejected(client: TestClient, headers):
    resp = client.post(
        "/crm/clients",
        json={"name": "X", "tags": [f"tag{i}" for i in range(60)]},
        headers=headers,
    )
    assert resp.status_code == 422


def test_failing_subscriber_does_not_break_move(client: TestClient, headers):
    def boom(**_payload):
        raise RuntimeError("assinante quebrou")

    events.subscribe("crm.client.moved", boom)
    try:
        c = client.post("/crm/clients", json={"name": "Resiliente"}, headers=headers).json()
        stages = client.get("/crm/stages", headers=headers).json()
        resp = client.post(
            f"/crm/clients/{c['id']}/move", json={"stage_id": stages[1]["id"]}, headers=headers
        )
    finally:
        events.clear()
    # move foi commitado e retornou 200 apesar do assinante falhar
    assert resp.status_code == 200
    assert resp.json()["stage_id"] == stages[1]["id"]


def test_update_client(client: TestClient, headers):
    c = client.post("/crm/clients", json={"name": "Antes"}, headers=headers).json()
    resp = client.patch(
        f"/crm/clients/{c['id']}",
        json={"name": "Depois", "phone": "+5511999999999"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Depois"
    assert resp.json()["phone"] == "+5511999999999"
