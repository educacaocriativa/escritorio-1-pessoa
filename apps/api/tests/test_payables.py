"""Testes de Contas a Pagar."""
import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Pag Co",
    "document": "10101010000111",
    "slug": "pagco",
    "email": "pag@example.com",
    "name": "Pag",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _bill(**over):
    base = {
        "description": "Aluguel",
        "category": "Estrutura",
        "supplier": "Imobiliária X",
        "amount_cents": 250000,
        "due_date": "2099-08-05",
    }
    return {**base, **over}


def test_create_bill(client: TestClient, headers):
    resp = client.post("/payables/bills", json=_bill(), headers=headers)
    assert resp.status_code == 201, resp.text
    b = resp.json()
    assert b["status"] == "open"
    assert b["category"] == "Estrutura"
    assert b["is_overdue"] is False


def test_create_bill_injects_agenda(client: TestClient, headers):
    client.post("/payables/bills", json=_bill(due_date="2099-08-05"), headers=headers)
    events = client.get(
        "/agenda/events",
        params={"start": "2099-08-01T00:00:00+00:00", "end": "2099-08-31T00:00:00+00:00"},
        headers=headers,
    ).json()
    assert "cobranca_pagar" in [e["kind"] for e in events]


def test_invalid_recurrence_rejected(client: TestClient, headers):
    resp = client.post("/payables/bills", json=_bill(recurrence="diaria"), headers=headers)
    assert resp.status_code == 422


def test_mark_paid(client: TestClient, headers):
    b = client.post("/payables/bills", json=_bill(), headers=headers).json()
    resp = client.post(f"/payables/bills/{b['id']}/pay", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "paid"
    assert resp.json()["paid_at"]


def test_paid_cannot_cancel(client: TestClient, headers):
    b = client.post("/payables/bills", json=_bill(), headers=headers).json()
    client.post(f"/payables/bills/{b['id']}/pay", headers=headers)
    resp = client.post(f"/payables/bills/{b['id']}/cancel", headers=headers)
    assert resp.status_code == 409


def test_summary_open_and_overdue(client: TestClient, headers):
    client.post(
        "/payables/bills", json=_bill(amount_cents=10000, due_date="2020-01-01"), headers=headers
    )
    client.post(
        "/payables/bills", json=_bill(amount_cents=20000, due_date="2099-01-01"), headers=headers
    )
    s = client.get("/payables/summary", headers=headers).json()
    assert s["overdue_cents"] == 10000
    assert s["open_cents"] == 20000


def test_categories_list(client: TestClient, headers):
    client.post("/payables/bills", json=_bill(category="Impostos"), headers=headers)
    client.post("/payables/bills", json=_bill(category="Marketing"), headers=headers)
    cats = client.get("/payables/categories", headers=headers).json()
    assert "Impostos" in cats and "Marketing" in cats


def test_requires_auth(client: TestClient):
    assert client.get("/payables/summary").status_code == 401
