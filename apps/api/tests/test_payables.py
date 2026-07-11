"""Testes de Contas a Pagar."""
import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Pag Co",
    "document": "10101010000177",
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


def test_create_bill_with_payment_code(client: TestClient, headers):
    b = client.post(
        "/payables/bills",
        json=_bill(payment_code="00020126-PIX", attachment_url="https://x.com/boleto.pdf"),
        headers=headers,
    ).json()
    assert b["payment_code"] == "00020126-PIX"
    assert b["attachment_url"] == "https://x.com/boleto.pdf"


def test_recurring_generates_occurrences(client: TestClient, headers):
    client.post(
        "/payables/bills",
        json=_bill(due_date="2026-08-05", recurrence="monthly", recurrence_count=3),
        headers=headers,
    )
    bills = client.get("/payables/bills", headers=headers).json()
    assert len(bills) == 3  # 3 contas geradas
    dues = sorted(b["due_date"] for b in bills)
    assert dues == ["2026-08-05", "2026-09-05", "2026-10-05"]  # vencimentos mensais
    groups = {b["recurrence_group"] for b in bills}
    assert len(groups) == 1 and None not in groups  # mesma recorrência
    # cada ocorrência tem seu evento na agenda (3 datas distintas)
    events = [e for e in client.get("/agenda/events?limit=500", headers=headers).json()
              if e["kind"] == "cobranca_pagar"]
    assert len(events) == 3


def test_edit_payable_moves_agenda(client: TestClient, headers):
    b = client.post("/payables/bills", json=_bill(due_date="2026-08-01"), headers=headers).json()
    resp = client.patch(
        f"/payables/bills/{b['id']}",
        json={"description": "Editado", "amount_cents": 99900, "due_date": "2026-08-20"},
        headers=headers,
    )
    assert resp.status_code == 200
    out = resp.json()
    assert out["description"] == "Editado"
    assert out["amount_cents"] == 99900
    assert out["due_date"] == "2026-08-20"
    ev = [e for e in client.get("/agenda/events?limit=500", headers=headers).json()
          if e["kind"] == "cobranca_pagar"][0]
    assert ev["starts_at"].startswith("2026-08-20")  # evento moveu junto
    assert ev["amount_cents"] == 99900


def test_cannot_edit_paid_payable(client: TestClient, headers):
    b = client.post("/payables/bills", json=_bill(), headers=headers).json()
    client.post(f"/payables/bills/{b['id']}/pay", headers=headers)
    resp = client.patch(f"/payables/bills/{b['id']}", json={"amount_cents": 5000}, headers=headers)
    assert resp.status_code == 409


def test_attach_boleto_after_creation(client: TestClient, headers):
    b = client.post("/payables/bills", json=_bill(), headers=headers).json()
    assert b["payment_code"] == ""
    resp = client.patch(
        f"/payables/bills/{b['id']}",
        json={"payment_code": "34191.79001 01043", "attachment_url": "https://x.com/b.pdf"},
        headers=headers,
    )
    assert resp.status_code == 200
    out = resp.json()
    assert out["payment_code"].startswith("34191")
    assert out["attachment_url"] == "https://x.com/b.pdf"


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


# ── Story 5.2: classificação (plano de contas) + competência ───────────────────────────────────


def test_payable_competence_defaults_to_due_date(client: TestClient, headers):
    """AC1/AC2: competência omitida → fallback = vencimento."""
    b = client.post("/payables/bills", json=_bill(due_date="2099-08-05"), headers=headers).json()
    assert b["competence_date"] == "2099-08-05"
    assert b["chart_account_id"] is None


def test_payable_accepts_explicit_competence(client: TestClient, headers):
    b = client.post(
        "/payables/bills",
        json=_bill(due_date="2099-09-30", competence_date="2099-08-31"),
        headers=headers,
    ).json()
    assert b["competence_date"] == "2099-08-31"
    assert b["due_date"] == "2099-09-30"


def test_payable_accepts_valid_chart_account(client: TestClient, headers):
    acc = client.post(
        "/chart-of-accounts",
        json={"grupo_dre": "DESPESA_FIXA", "categoria": "Aluguel"},
        headers=headers,
    ).json()
    b = client.post(
        "/payables/bills", json=_bill(chart_account_id=acc["id"]), headers=headers
    ).json()
    assert b["chart_account_id"] == acc["id"]


def test_payable_rejects_unknown_chart_account(client: TestClient, headers):
    resp = client.post(
        "/payables/bills", json=_bill(chart_account_id="nao-existe"), headers=headers
    )
    assert resp.status_code == 404, resp.text


def test_recurring_payable_competence_advances(client: TestClient, headers):
    client.post(
        "/payables/bills",
        json=_bill(due_date="2026-08-05", competence_date="2026-08-01",
                   recurrence="monthly", recurrence_count=3),
        headers=headers,
    )
    bills = client.get("/payables/bills", headers=headers).json()
    comps = sorted(b["competence_date"] for b in bills)
    assert comps == ["2026-08-01", "2026-09-01", "2026-10-01"]


def test_reclassify_payable(client: TestClient, headers):
    acc = client.post(
        "/chart-of-accounts",
        json={"grupo_dre": "TRIBUTOS", "categoria": "ISS"},
        headers=headers,
    ).json()
    b = client.post("/payables/bills", json=_bill(), headers=headers).json()
    resp = client.patch(
        f"/payables/bills/{b['id']}",
        json={"competence_date": "2099-07-31", "chart_account_id": acc["id"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["competence_date"] == "2099-07-31"
    assert out["chart_account_id"] == acc["id"]
