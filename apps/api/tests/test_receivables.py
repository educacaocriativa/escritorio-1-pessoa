"""Testes de Contas a Receber — incluindo a baixa que alimenta a Carteira com split."""
import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Cobra Co",
    "document": "77888999000122",
    "slug": "cobraco",
    "email": "cobra@example.com",
    "name": "Cobra",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _charge(**over):
    base = {
        "kind": "service",
        "method": "pix",
        "amount_cents": 10000,
        "due_date": "2026-08-10",
        "description": "Mensalidade",
    }
    return {**base, **over}


def test_create_charge_generates_code(client: TestClient, headers):
    resp = client.post("/receivables/charges", json=_charge(), headers=headers)
    assert resp.status_code == 201, resp.text
    c = resp.json()
    assert c["status"] == "open"
    assert c["payment_code"]  # gateway stub
    assert c["is_overdue"] is False


def test_create_charge_injects_agenda_event(client: TestClient, headers):
    client.post("/receivables/charges", json=_charge(due_date="2026-08-10"), headers=headers)
    # o vencimento aparece na agenda como cobranca_receber
    events = client.get(
        "/agenda/events",
        params={"start": "2026-08-01T00:00:00+00:00", "end": "2026-08-31T00:00:00+00:00"},
        headers=headers,
    ).json()
    kinds = [e["kind"] for e in events]
    assert "cobranca_receber" in kinds


def test_pay_charge_feeds_wallet_with_split(client: TestClient, headers):
    charge = client.post(
        "/receivables/charges", json=_charge(amount_cents=10000), headers=headers
    ).json()
    # antes de pagar, carteira zerada
    assert client.get("/wallet/summary", headers=headers).json()["available_cents"] == 0

    paid = client.post(f"/receivables/charges/{charge['id']}/pay", headers=headers).json()
    assert paid["status"] == "paid"
    assert paid["transaction_id"]

    # serviço pix 30% -> líquido 7000 disponível
    s = client.get("/wallet/summary", headers=headers).json()
    assert s["available_cents"] == 7000
    assert s["fees_total_cents"] == 3000


def test_pay_twice_is_idempotent(client: TestClient, headers):
    charge = client.post("/receivables/charges", json=_charge(), headers=headers).json()
    client.post(f"/receivables/charges/{charge['id']}/pay", headers=headers)
    client.post(f"/receivables/charges/{charge['id']}/pay", headers=headers)
    # não duplica receita na carteira
    assert client.get("/wallet/summary", headers=headers).json()["available_cents"] == 7000


def test_cancel_then_pay_rejected(client: TestClient, headers):
    charge = client.post("/receivables/charges", json=_charge(), headers=headers).json()
    client.post(f"/receivables/charges/{charge['id']}/cancel", headers=headers)
    resp = client.post(f"/receivables/charges/{charge['id']}/pay", headers=headers)
    assert resp.status_code == 409


def test_overdue_summary(client: TestClient, headers):
    client.post("/receivables/charges", json=_charge(due_date="2020-01-01"), headers=headers)
    client.post("/receivables/charges", json=_charge(due_date="2099-01-01"), headers=headers)
    s = client.get("/receivables/summary", headers=headers).json()
    assert s["overdue_cents"] == 10000
    assert s["open_cents"] == 10000
    assert s["overdue_count"] == 1


def test_collect_with_ai_writes_message_and_notifies(client: TestClient, headers):
    # sem ANTHROPIC_API_KEY nos testes, usa o template (não chama o Claude)
    c = client.post(
        "/receivables/charges",
        json=_charge(due_date="2020-01-01", amount_cents=15000),
        headers=headers,
    ).json()
    r = client.post(f"/receivables/charges/{c['id']}/collect", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body["message"]) > 10
    assert body["status"] == "logged"
    # uma notificação de WhatsApp foi registrada
    notifs = client.get("/notifications", headers=headers).json()
    assert any(n["channel"] == "whatsapp" for n in notifs)


def test_collect_only_open(client: TestClient, headers):
    c = client.post("/receivables/charges", json=_charge(), headers=headers).json()
    client.post(f"/receivables/charges/{c['id']}/pay", headers=headers)  # paga
    resp = client.post(f"/receivables/charges/{c['id']}/collect", headers=headers)
    assert resp.status_code == 409


def test_charge_shows_client_name(client: TestClient, headers):
    cl = client.post("/crm/clients", json={"name": "João Cobrado"}, headers=headers).json()
    client.post("/receivables/charges", json=_charge(client_id=cl["id"]), headers=headers)
    charges = client.get("/receivables/charges", headers=headers).json()
    assert charges[0]["client_name"] == "João Cobrado"


def test_requires_auth(client: TestClient):
    assert client.get("/receivables/summary").status_code == 401
