"""Testes da Ficha 360° do cliente: trocar vencimento, protestar e filtros por cliente."""
import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Ficha SA",
    "document": "26262626000177",
    "slug": "fichasa",
    "email": "ficha@example.com",
    "name": "Fi",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _charge(client, headers, *, client_id=None, due="2020-01-01", amount=10000):
    body = {"kind": "service", "method": "pix", "amount_cents": amount, "due_date": due}
    if client_id:
        body["client_id"] = client_id
    return client.post("/receivables/charges", json=body, headers=headers).json()


def test_reschedule_moves_due_date(client: TestClient, headers):
    ch = _charge(client, headers, due="2026-07-01")
    resp = client.post(
        f"/receivables/charges/{ch['id']}/reschedule",
        json={"due_date": "2026-09-15"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["due_date"] == "2026-09-15"


def test_reschedule_updates_agenda_event(client: TestClient, headers):
    ch = _charge(client, headers, due="2026-07-01")
    client.post(
        f"/receivables/charges/{ch['id']}/reschedule",
        json={"due_date": "2026-08-20"},
        headers=headers,
    )
    events = client.get("/agenda/events?limit=500", headers=headers).json()
    ev = [e for e in events if e["kind"] == "cobranca_receber"][0]
    assert ev["starts_at"].startswith("2026-08-20")


def test_cannot_reschedule_paid(client: TestClient, headers):
    ch = _charge(client, headers, due="2026-07-01")
    client.post(f"/receivables/charges/{ch['id']}/pay", headers=headers)
    resp = client.post(
        f"/receivables/charges/{ch['id']}/reschedule",
        json={"due_date": "2026-09-01"},
        headers=headers,
    )
    assert resp.status_code == 409


def test_protest_overdue_charge(client: TestClient, headers):
    ch = _charge(client, headers, due="2020-01-01")  # vencida
    resp = client.post(f"/receivables/charges/{ch['id']}/protest", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["protested_at"] is not None


def test_cannot_protest_not_overdue(client: TestClient, headers):
    ch = _charge(client, headers, due="2030-01-01")  # a vencer
    resp = client.post(f"/receivables/charges/{ch['id']}/protest", headers=headers)
    assert resp.status_code == 409


def test_cannot_protest_paid(client: TestClient, headers):
    ch = _charge(client, headers, due="2020-01-01")
    client.post(f"/receivables/charges/{ch['id']}/pay", headers=headers)
    resp = client.post(f"/receivables/charges/{ch['id']}/protest", headers=headers)
    assert resp.status_code == 409


def test_charges_filtered_by_client(client: TestClient, headers):
    a = client.post("/crm/clients", json={"name": "Cliente A"}, headers=headers).json()
    b = client.post("/crm/clients", json={"name": "Cliente B"}, headers=headers).json()
    _charge(client, headers, client_id=a["id"], amount=11100)
    _charge(client, headers, client_id=b["id"], amount=22200)
    only_a = client.get(f"/receivables/charges?client_id={a['id']}", headers=headers).json()
    assert len(only_a) == 1
    assert only_a[0]["amount_cents"] == 11100


def test_contracts_and_quotes_filtered_by_client(client: TestClient, headers):
    a = client.post("/crm/clients", json={"name": "Cliente A"}, headers=headers).json()
    b = client.post("/crm/clients", json={"name": "Cliente B"}, headers=headers).json()
    client.post(
        "/contracts",
        json={"title": "C-A", "client_id": a["id"], "clauses": [{"title": "x", "text": "y"}]},
        headers=headers,
    )
    client.post(
        "/quotes",
        json={"title": "Q-B", "client_id": b["id"],
              "items": [{"description": "i", "quantity": 1, "unit_price_cents": 1000}]},
        headers=headers,
    )
    ca = client.get(f"/contracts?client_id={a['id']}", headers=headers).json()
    qb = client.get(f"/quotes?client_id={b['id']}", headers=headers).json()
    assert len(ca) == 1 and ca[0]["title"] == "C-A"
    assert len(qb) == 1 and qb[0]["title"] == "Q-B"
    # cruzado: cliente A não tem orçamentos
    assert client.get(f"/quotes?client_id={a['id']}", headers=headers).json() == []
