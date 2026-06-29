"""Testes da Central de Orçamentos — incluindo o efeito dominó (aprovar -> cobrança)."""
import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Orca Co",
    "document": "18181818000199",
    "slug": "orcaco",
    "email": "orca@example.com",
    "name": "Or",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _quote(**over):
    base = {
        "title": "Consultoria",
        "items": [
            {"description": "Hora técnica", "quantity": 10, "unit_price_cents": 15000},
            {"description": "Relatório", "quantity": 1, "unit_price_cents": 50000},
        ],
        "discount_cents": 0,
    }
    return {**base, **over}


def test_create_computes_totals(client: TestClient, headers):
    resp = client.post("/quotes", json=_quote(), headers=headers)
    assert resp.status_code == 201, resp.text
    q = resp.json()
    assert q["subtotal_cents"] == 200000  # 10*15000 + 50000
    assert q["total_cents"] == 200000
    assert q["status"] == "draft"


def test_discount_applied(client: TestClient, headers):
    q = client.post("/quotes", json=_quote(discount_cents=20000), headers=headers).json()
    assert q["total_cents"] == 180000


def test_requires_at_least_one_item(client: TestClient, headers):
    resp = client.post("/quotes", json=_quote(items=[]), headers=headers)
    assert resp.status_code == 422


def test_send_marks_sent_and_notifies(client: TestClient, headers):
    cl = client.post("/crm/clients", json={"name": "Cliente Orca"}, headers=headers).json()
    q = client.post("/quotes", json=_quote(client_id=cl["id"]), headers=headers).json()
    resp = client.post(f"/quotes/{q['id']}/send", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "sent"
    notifs = client.get("/notifications", headers=headers).json()
    assert any(n["channel"] == "whatsapp" for n in notifs)


def test_approve_generates_charge(client: TestClient, headers):
    cl = client.post("/crm/clients", json={"name": "Cliente Orca"}, headers=headers).json()
    q = client.post("/quotes", json=_quote(client_id=cl["id"]), headers=headers).json()
    resp = client.post(f"/quotes/{q['id']}/approve", headers=headers)
    assert resp.status_code == 200
    approved = resp.json()
    assert approved["status"] == "approved"
    assert approved["charge_id"]
    # a cobrança foi criada em Contas a Receber pelo valor total
    charges = client.get("/receivables/charges", headers=headers).json()
    assert any(c["amount_cents"] == 200000 for c in charges)


def test_approve_zero_total_rejected(client: TestClient, headers):
    q = client.post(
        "/quotes",
        json={
            "title": "Brinde",
            "items": [{"description": "X", "quantity": 1, "unit_price_cents": 0}],
        },
        headers=headers,
    ).json()
    resp = client.post(f"/quotes/{q['id']}/approve", headers=headers)
    assert resp.status_code == 409  # não 500


def test_reject(client: TestClient, headers):
    q = client.post("/quotes", json=_quote(), headers=headers).json()
    resp = client.post(f"/quotes/{q['id']}/reject", headers=headers)
    assert resp.json()["status"] == "rejected"


def test_cannot_edit_after_sent(client: TestClient, headers):
    q = client.post("/quotes", json=_quote(), headers=headers).json()
    client.post(f"/quotes/{q['id']}/send", headers=headers)
    resp = client.patch(f"/quotes/{q['id']}", json={"title": "Novo"}, headers=headers)
    assert resp.status_code == 409


def test_summary(client: TestClient, headers):
    q1 = client.post("/quotes", json=_quote(), headers=headers).json()
    client.post(f"/quotes/{q1['id']}/approve", headers=headers)
    client.post("/quotes", json=_quote(), headers=headers)  # draft
    s = client.get("/quotes/summary", headers=headers).json()
    assert s["approved_cents"] == 200000
    assert s["draft_count"] == 1


def test_requires_auth(client: TestClient):
    assert client.get("/quotes/summary").status_code == 401
