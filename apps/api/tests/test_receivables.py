"""Testes de Contas a Receber — incluindo a baixa que alimenta a Carteira com split."""
import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Cobra Co",
    "document": "77888999000181",
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


def test_boleto_charge_generates_pdf_attachment(client: TestClient, headers):
    c = client.post("/receivables/charges", json=_charge(method="boleto"), headers=headers).json()
    atts = client.get(
        f"/attachments?owner_type=charge&owner_id={c['id']}", headers=headers
    ).json()
    boleto = [a for a in atts if a["label"] == "boleto"]
    assert boleto and boleto[0]["content_type"] == "application/pdf"
    assert boleto[0]["size"] > 0


def test_webhook_recognizes_payment_and_credits_wallet(client: TestClient, headers):
    c = client.post("/receivables/charges", json=_charge(method="boleto"), headers=headers).json()
    # gateway confirma o pagamento (sem login, sem ação do dono)
    resp = client.post(
        "/receivables/webhook",
        json={"tenant_id": c["tenant_id"], "charge_id": c["id"], "status": "paid"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "paid"
    # cobrança paga e Carteira creditada (disponível para saque)
    got = client.get(f"/receivables/charges/{c['id']}", headers=headers).json()
    assert got["status"] == "paid"
    wallet = client.get("/wallet/summary", headers=headers).json()
    assert wallet["available_cents"] > 0


def test_recurring_charge_generates_occurrences(client: TestClient, headers):
    client.post(
        "/receivables/charges",
        json=_charge(due_date="2026-08-10", method="boleto", recurrence="monthly",
                     recurrence_count=4),
        headers=headers,
    )
    charges = client.get("/receivables/charges", headers=headers).json()
    assert len(charges) == 4
    dues = sorted(c["due_date"] for c in charges)
    assert dues == ["2026-08-10", "2026-09-10", "2026-10-10", "2026-11-10"]
    groups = {c["recurrence_group"] for c in charges}
    assert len(groups) == 1 and None not in groups
    # cada uma com seu código de boleto próprio
    assert all(c["payment_code"] for c in charges)


def test_edit_charge_moves_agenda(client: TestClient, headers):
    c = client.post(
        "/receivables/charges", json=_charge(due_date="2026-08-10"), headers=headers
    ).json()
    resp = client.patch(
        f"/receivables/charges/{c['id']}",
        json={"description": "Nova descrição", "amount_cents": 33300, "due_date": "2026-09-05"},
        headers=headers,
    )
    assert resp.status_code == 200
    out = resp.json()
    assert out["amount_cents"] == 33300
    assert out["due_date"] == "2026-09-05"
    ev = [e for e in client.get("/agenda/events?limit=500", headers=headers).json()
          if e["kind"] == "cobranca_receber"][0]
    assert ev["starts_at"].startswith("2026-09-05")  # evento moveu junto
    assert ev["amount_cents"] == 33300


def test_cannot_edit_paid_charge(client: TestClient, headers):
    c = client.post("/receivables/charges", json=_charge(), headers=headers).json()
    client.post(f"/receivables/charges/{c['id']}/pay", headers=headers)
    resp = client.patch(
        f"/receivables/charges/{c['id']}", json={"amount_cents": 5000}, headers=headers
    )
    assert resp.status_code == 409


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


def test_message_history_and_manual_message(client: TestClient, headers):
    cl = client.post("/crm/clients", json={"name": "Cliente Msg"}, headers=headers).json()
    c = client.post(
        "/receivables/charges",
        json=_charge(client_id=cl["id"], due_date="2020-01-01"),
        headers=headers,
    ).json()
    # cobrança com IA + mensagem manual
    client.post(f"/receivables/charges/{c['id']}/collect", headers=headers)
    r = client.post(
        f"/receivables/charges/{c['id']}/message",
        json={"text": "Oi, passando para lembrar 🙂"},
        headers=headers,
    )
    assert r.status_code == 200
    # histórico mostra as duas mensagens
    msgs = client.get(f"/receivables/charges/{c['id']}/messages", headers=headers).json()
    assert len(msgs) == 2
    assert any("lembrar" in m["message"] for m in msgs)


def test_messages_empty_without_client(client: TestClient, headers):
    c = client.post("/receivables/charges", json=_charge(), headers=headers).json()  # sem cliente
    msgs = client.get(f"/receivables/charges/{c['id']}/messages", headers=headers).json()
    assert msgs == []


def test_get_single_charge(client: TestClient, headers):
    c = client.post("/receivables/charges", json=_charge(), headers=headers).json()
    got = client.get(f"/receivables/charges/{c['id']}", headers=headers).json()
    assert got["id"] == c["id"]


def test_requires_auth(client: TestClient):
    assert client.get("/receivables/summary").status_code == 401
