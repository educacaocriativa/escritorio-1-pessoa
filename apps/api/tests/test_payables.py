"""Testes de Contas a Pagar.

⚠️ **Adaptado pela Story 8.12, não reescrito.** A baixa passou a exigir a conta bancária de onde o
dinheiro saiu (`POST /bills/{id}/pay` com corpo obrigatório) e a data de caixa passou a ter teto em
hoje. Os testes que davam baixa ganharam a fixture `conta` e o helper `_pay`; **nenhuma asserção de
comportamento antigo foi enfraquecida ou apagada**. O que a 8.12 acrescenta de novo vive em
`test_payables_bank_origin.py`.
"""
from datetime import UTC, date, datetime

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

# Abertura bem no passado: o piso da data de baixa é `paid_on > opening_date` e as contas destes
# testes vencem em 2099 (pagas com `paid_on` = hoje).
ABERTURA = date(2026, 1, 1)


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def conta(client: TestClient, headers) -> str:
    """A conta bancária de onde o dinheiro sai. **Obrigatória na baixa desde a Story 8.12** (F7)."""
    resp = client.post(
        "/bank/accounts",
        json={
            "name": "Itaú PJ",
            "kind": "checking",
            "opening_balance_cents": 500_000,
            "opening_date": ABERTURA.isoformat(),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _hoje() -> str:
    return datetime.now(UTC).date().isoformat()


def _pay(client: TestClient, headers, bill_id: str, conta: str, paid_on: str | None = None):
    """`POST /bills/{id}/pay` com o corpo que a Story 8.12 tornou obrigatório (AC11).

    `paid_on` default = **hoje** aqui (e não o `due_date` do service): as contas deste arquivo
    vencem em 2099, e o teto do AC3 recusaria a data futura.
    """
    body = {"bank_account_id": conta, "paid_on": paid_on or _hoje()}
    return client.post(f"/payables/bills/{bill_id}/pay", json=body, headers=headers)


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


def test_cannot_edit_paid_payable(client: TestClient, headers, conta):
    b = client.post("/payables/bills", json=_bill(), headers=headers).json()
    _pay(client, headers, b["id"], conta)
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


def test_mark_paid(client: TestClient, headers, conta):
    b = client.post("/payables/bills", json=_bill(), headers=headers).json()
    resp = _pay(client, headers, b["id"], conta)
    assert resp.status_code == 200
    assert resp.json()["status"] == "paid"
    assert resp.json()["paid_at"]


def test_paid_cannot_cancel(client: TestClient, headers, conta):
    b = client.post("/payables/bills", json=_bill(), headers=headers).json()
    _pay(client, headers, b["id"], conta)
    resp = client.post(f"/payables/bills/{b['id']}/cancel", headers=headers)
    assert resp.status_code == 409


def test_scheduled_cannot_cancel(client: TestClient, headers, conta):
    """BANK-002 (QA gate da Onda 2): cancelar uma conta agendada sem recusar deixava o
    bank_transaction de débito futuro órfão — divergência inventada na conferência, invisível
    ao gate P1-P4 porque `canceled` sai da população de "sem conta informada". Espelha
    test_receivables_off_rail.py::test_scheduled_cannot_cancel."""
    b = client.post(
        "/payables/bills",
        json=_bill(amount_cents=12345, due_date="2099-01-01"),
        headers=headers,
    ).json()
    pay_resp = _pay(client, headers, b["id"], conta, paid_on="2099-01-01")
    assert pay_resp.json()["status"] == "scheduled"

    resp = client.post(f"/payables/bills/{b['id']}/cancel", headers=headers)
    assert resp.status_code == 409

    movs = client.get(
        "/bank/transactions", params={"bank_account_id": conta}, headers=headers
    ).json()
    assert any(m["amount_cents"] == -12345 and m["posted_at"] == "2099-01-01" for m in movs), (
        "o débito futuro tem que continuar de pé — cancelar foi recusado, não silenciosamente "
        "aceito com o débito órfão"
    )


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


def test_unset_payable_chart_account(client: TestClient, headers):
    """"" desvincula (→ sem categoria), mesmo padrão de contract_id/cost_center_id."""
    acc = client.post(
        "/chart-of-accounts",
        json={"grupo_dre": "DESPESA_FIXA", "categoria": "Aluguel"},
        headers=headers,
    ).json()
    b = client.post(
        "/payables/bills", json=_bill(chart_account_id=acc["id"]), headers=headers
    ).json()
    resp = client.patch(
        f"/payables/bills/{b['id']}", json={"chart_account_id": ""}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["chart_account_id"] is None


def test_reverse_paid_payable(client: TestClient, headers, conta):
    b = client.post("/payables/bills", json=_bill(due_date="2026-08-05"), headers=headers).json()
    _pay(client, headers, b["id"], conta)

    resp = client.post(f"/payables/bills/{b['id']}/reverse", headers=headers)
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["status"] == "open"
    assert out["paid_at"] is None

    # evento na Agenda volta a aparecer como pendente (não mais "concluído")
    ev = [e for e in client.get("/agenda/events?limit=500", headers=headers).json()
          if e["kind"] == "cobranca_pagar"][0]
    assert ev["status"] == "scheduled"

    # reaberta, volta a poder editar dados
    edit = client.patch(
        f"/payables/bills/{b['id']}", json={"amount_cents": 12345}, headers=headers
    )
    assert edit.status_code == 200
    assert edit.json()["amount_cents"] == 12345


def test_reverse_open_payable_rejected(client: TestClient, headers):
    b = client.post("/payables/bills", json=_bill(), headers=headers).json()
    resp = client.post(f"/payables/bills/{b['id']}/reverse", headers=headers)
    assert resp.status_code == 409


def test_reverse_canceled_payable_rejected(client: TestClient, headers):
    b = client.post("/payables/bills", json=_bill(), headers=headers).json()
    client.post(f"/payables/bills/{b['id']}/cancel", headers=headers)
    resp = client.post(f"/payables/bills/{b['id']}/reverse", headers=headers)
    assert resp.status_code == 409
