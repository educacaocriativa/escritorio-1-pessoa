"""Testes da Fila de Pagamentos (Story 5.9).

Foco nas datas de BORDA dos baldes (hoje / +7 / +30) — o erro mais fácil aqui é off-by-one. As
datas são calculadas relativas a `hoje` (a fila usa `datetime.now(UTC).date()` por padrão), então os
testes não dependem de uma data fixa no calendário.

Regras dos baldes:
  - atrasados:        due_date <  hoje
  - hoje:             due_date == hoje
  - proximos_7_dias:  hoje    <  due_date <= hoje+7
  - proximos_30_dias: hoje+7  <  due_date <= hoje+30
  - > hoje+30 → FORA da fila (não é "próximo")
"""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Fila Co",
    "document": "10101010000177",
    "slug": "filaco",
    "email": "fila@example.com",
    "name": "Fila",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _today():
    return datetime.now(UTC).date()


def _ymd(days: int) -> str:
    return (_today() + timedelta(days=days)).isoformat()


def _bill(**over):
    base = {"description": "Conta", "amount_cents": 10000, "due_date": _ymd(3)}
    return {**base, **over}


def _create(client: TestClient, headers, **over):
    resp = client.post("/payables/bills", json=_bill(**over), headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_queue_requires_auth(client: TestClient):
    assert client.get("/payables/queue").status_code == 401


def test_queue_empty(client: TestClient, headers):
    q = client.get("/payables/queue", headers=headers).json()
    for bucket in ("atrasados", "hoje", "proximos_7_dias", "proximos_30_dias"):
        assert q[bucket] == []
    s = q["summary"]
    assert s["atrasados_count"] == 0 and s["atrasados_cents"] == 0
    assert s["hoje_count"] == 0 and s["proximos_7_dias_count"] == 0


def test_queue_groups_by_window(client: TestClient, headers):
    _create(client, headers, due_date=_ymd(-1), amount_cents=1000)  # atrasado
    _create(client, headers, due_date=_ymd(0), amount_cents=2000)  # hoje
    _create(client, headers, due_date=_ymd(3), amount_cents=3000)  # próximos 7
    _create(client, headers, due_date=_ymd(20), amount_cents=4000)  # próximos 30

    q = client.get("/payables/queue", headers=headers).json()
    assert [p["amount_cents"] for p in q["atrasados"]] == [1000]
    assert [p["amount_cents"] for p in q["hoje"]] == [2000]
    assert [p["amount_cents"] for p in q["proximos_7_dias"]] == [3000]
    assert [p["amount_cents"] for p in q["proximos_30_dias"]] == [4000]
    # o item atrasado carrega is_overdue=True (reaproveita is_overdue)
    assert q["atrasados"][0]["is_overdue"] is True
    assert q["hoje"][0]["is_overdue"] is False


def test_queue_boundary_today_is_hoje_not_overdue(client: TestClient, headers):
    """Borda: vencimento EXATAMENTE hoje → balde 'hoje', nunca 'atrasados'."""
    _create(client, headers, due_date=_ymd(0))
    q = client.get("/payables/queue", headers=headers).json()
    assert len(q["hoje"]) == 1
    assert q["atrasados"] == []


def test_queue_boundary_day_7_is_proximos_7(client: TestClient, headers):
    """Borda: vencimento EXATAMENTE em hoje+7 → 'proximos_7_dias' (limite inclusivo)."""
    _create(client, headers, due_date=_ymd(7))
    q = client.get("/payables/queue", headers=headers).json()
    assert len(q["proximos_7_dias"]) == 1
    assert q["proximos_30_dias"] == []


def test_queue_boundary_day_8_is_proximos_30(client: TestClient, headers):
    """Borda: hoje+8 já saiu da janela de 7 dias → cai em 'proximos_30_dias'."""
    _create(client, headers, due_date=_ymd(8))
    q = client.get("/payables/queue", headers=headers).json()
    assert q["proximos_7_dias"] == []
    assert len(q["proximos_30_dias"]) == 1


def test_queue_boundary_day_30_is_proximos_30(client: TestClient, headers):
    """Borda: vencimento EXATAMENTE em hoje+30 → 'proximos_30_dias' (limite inclusivo)."""
    _create(client, headers, due_date=_ymd(30))
    q = client.get("/payables/queue", headers=headers).json()
    assert len(q["proximos_30_dias"]) == 1


def test_queue_beyond_30_days_excluded(client: TestClient, headers):
    """hoje+31 não é 'próximo' — fica FORA da fila (mas continua em Contas a Pagar)."""
    _create(client, headers, due_date=_ymd(31))
    q = client.get("/payables/queue", headers=headers).json()
    for bucket in ("atrasados", "hoje", "proximos_7_dias", "proximos_30_dias"):
        assert q[bucket] == []
    # segue existente na lista completa de Contas a Pagar (não é a fila que o some)
    assert len(client.get("/payables/bills", headers=headers).json()) == 1


def test_queue_summary_counts_and_sums(client: TestClient, headers):
    _create(client, headers, due_date=_ymd(-2), amount_cents=1000)
    _create(client, headers, due_date=_ymd(-1), amount_cents=1500)
    _create(client, headers, due_date=_ymd(0), amount_cents=2000)
    _create(client, headers, due_date=_ymd(5), amount_cents=3000)

    s = client.get("/payables/queue", headers=headers).json()["summary"]
    assert s["atrasados_count"] == 2 and s["atrasados_cents"] == 2500
    assert s["hoje_count"] == 1 and s["hoje_cents"] == 2000
    assert s["proximos_7_dias_count"] == 1 and s["proximos_7_dias_cents"] == 3000
    assert s["proximos_30_dias_count"] == 0 and s["proximos_30_dias_cents"] == 0


def test_queue_only_open_bills(client: TestClient, headers):
    """Fila só mostra contas EM ABERTO — pagas e canceladas não aparecem."""
    paid = _create(client, headers, due_date=_ymd(2), amount_cents=5000)
    canceled = _create(client, headers, due_date=_ymd(2), amount_cents=6000)
    _create(client, headers, due_date=_ymd(2), amount_cents=7000)  # segue em aberto
    client.post(f"/payables/bills/{paid['id']}/pay", headers=headers)
    client.post(f"/payables/bills/{canceled['id']}/cancel", headers=headers)

    q = client.get("/payables/queue", headers=headers).json()
    assert [p["amount_cents"] for p in q["proximos_7_dias"]] == [7000]


def test_mark_paid_from_queue_reflects_same_payable(client: TestClient, headers):
    """Baixa em um clique pela fila reusa mark_paid — mesmo Payable de Contas a Pagar, sem duplicar.
    Após pagar, o item sai da fila e o MESMO registro aparece 'paid' em /bills/{id}."""
    bill = _create(client, headers, due_date=_ymd(1), amount_cents=8800)
    # o mesmo endpoint que Contas a Pagar usa (nenhum endpoint de pagamento novo)
    pay = client.post(f"/payables/bills/{bill['id']}/pay", headers=headers)
    assert pay.status_code == 200
    assert pay.json()["status"] == "paid"
    assert pay.json()["paid_at"]  # auditoria mínima (quando pagou)

    # 1) o item sumiu da fila (não está mais em aberto)
    q = client.get("/payables/queue", headers=headers).json()
    assert all(p["id"] != bill["id"] for p in q["proximos_7_dias"])
    # 2) é o MESMO registro — /bills/{id} (tela de Contas a Pagar) reflete o pagamento
    same = client.get(f"/payables/bills/{bill['id']}", headers=headers).json()
    assert same["id"] == bill["id"] and same["status"] == "paid"


def test_queue_orders_by_due_date_within_bucket(client: TestClient, headers):
    """Dentro de um balde, os itens vêm ordenados por vencimento (order_by due_date)."""
    _create(client, headers, due_date=_ymd(6), amount_cents=600)
    _create(client, headers, due_date=_ymd(2), amount_cents=200)
    _create(client, headers, due_date=_ymd(4), amount_cents=400)
    q = client.get("/payables/queue", headers=headers).json()
    assert [p["amount_cents"] for p in q["proximos_7_dias"]] == [200, 400, 600]
