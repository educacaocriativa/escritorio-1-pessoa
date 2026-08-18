"""Testes da Fila de Pagamentos (Story 5.9).

Foco nas datas de BORDA dos baldes (hoje / +7 / +30) — o erro mais fácil aqui é off-by-one. As
datas são calculadas relativas a `hoje` (a fila usa o dia no FUSO DO TENANT por padrão — ver
`core/tz.tenant_today`), então os testes não dependem de uma data fixa no calendário.

Regras dos baldes:
  - atrasados:        due_date <  hoje
  - hoje:             due_date == hoje
  - proximos_7_dias:  hoje    <  due_date <= hoje+7
  - proximos_30_dias: hoje+7  <  due_date <= hoje+30
  - > hoje+30 → FORA da fila (não é "próximo")
"""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.tz import DEFAULT_TENANT_TIMEZONE, tenant_today

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
    """A MESMA âncora do service — fuso do tenant, nunca UTC (ver `core/tz.tenant_today`)."""
    return tenant_today(DEFAULT_TENANT_TIMEZONE)


def _ymd(days: int) -> str:
    return (_today() + timedelta(days=days)).isoformat()


def _bill(**over):
    base = {"description": "Conta", "amount_cents": 10000, "due_date": _ymd(3)}
    return {**base, **over}


def _create(client: TestClient, headers, **over):
    resp = client.post("/payables/bills", json=_bill(**over), headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture()
def conta(client: TestClient, headers) -> str:
    """A conta bancária da baixa — **obrigatória desde a Story 8.12** (AC1/AC11).

    A Fila de Pagamentos NÃO ganhou endpoint próprio: ela reusa `POST /payables/bills/{id}/pay`,
    então a mudança de contrato daquele endpoint alcança esta tela também (IV4). O backend da fila
    (`service.payment_queue`) não foi editado.
    """
    resp = client.post(
        "/bank/accounts",
        json={
            "name": "Itaú PJ",
            "kind": "checking",
            "opening_balance_cents": 500_000,
            "opening_balance_is_known": True,
            "opening_date": (_today() - timedelta(days=180)).isoformat(),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _pay(client: TestClient, headers, bill_id: str, conta: str):
    """A baixa pela fila, com o corpo obrigatório do AC11. `paid_on` = hoje."""
    return client.post(
        f"/payables/bills/{bill_id}/pay",
        json={"bank_account_id": conta, "paid_on": _today().isoformat()},
        headers=headers,
    )


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
    assert len(client.get("/payables/bills", headers=headers).json()["items"]) == 1


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


def test_queue_only_open_bills(client: TestClient, headers, conta):
    """Fila só mostra contas EM ABERTO — pagas e canceladas não aparecem."""
    paid = _create(client, headers, due_date=_ymd(2), amount_cents=5000)
    canceled = _create(client, headers, due_date=_ymd(2), amount_cents=6000)
    _create(client, headers, due_date=_ymd(2), amount_cents=7000)  # segue em aberto
    _pay(client, headers, paid["id"], conta)
    client.post(f"/payables/bills/{canceled['id']}/cancel", headers=headers)

    q = client.get("/payables/queue", headers=headers).json()
    assert [p["amount_cents"] for p in q["proximos_7_dias"]] == [7000]


def test_mark_paid_from_queue_reflects_same_payable(client: TestClient, headers, conta):
    """Baixa em um clique pela fila reusa mark_paid — mesmo Payable de Contas a Pagar, sem duplicar.
    Após pagar, o item sai da fila e o MESMO registro aparece 'paid' em /bills/{id}."""
    bill = _create(client, headers, due_date=_ymd(1), amount_cents=8800)
    # o mesmo endpoint que Contas a Pagar usa (nenhum endpoint de pagamento novo)
    pay = _pay(client, headers, bill["id"], conta)
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


# ── Story 8.14 — o QUINTO balde, e os quatro antigos intocados ────────────────────────────────


def _agendar(client: TestClient, headers, bill_id: str, conta: str, dias: int):
    """Baixa com data FUTURA → a conta nasce `scheduled` (o estado é derivado da data, AC2)."""
    resp = client.post(
        f"/payables/bills/{bill_id}/pay",
        json={"bank_account_id": conta, "paid_on": _ymd(dias)},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "scheduled", "pré-condição: a conta tinha de nascer agendada"
    return resp.json()


def test_os_QUATRO_baldes_antigos_nao_mudaram_sem_agendamento_nenhum(
    client: TestClient, headers
):
    """**IV2 em forma de snapshot:** num cenário sem agendamento, a fila é byte a byte a de antes.

    Os campos novos (`agendadas`, `agendadas_count`, `agendadas_cents`) aparecem **zerados**, nunca
    ausentes — um consumidor que os leia sem checar existência não quebra.
    """
    _create(client, headers, due_date=_ymd(-2), amount_cents=100)
    _create(client, headers, due_date=_ymd(0), amount_cents=200)
    _create(client, headers, due_date=_ymd(5), amount_cents=300)
    _create(client, headers, due_date=_ymd(20), amount_cents=400)

    q = client.get("/payables/queue", headers=headers).json()
    assert q["summary"] == {
        "atrasados_count": 1, "atrasados_cents": 100,
        "hoje_count": 1, "hoje_cents": 200,
        "proximos_7_dias_count": 1, "proximos_7_dias_cents": 300,
        "proximos_30_dias_count": 1, "proximos_30_dias_cents": 400,
        "agendadas_count": 0, "agendadas_cents": 0,
    }
    assert q["agendadas"] == []


def test_a_agendada_SAI_dos_quatro_baldes_de_vencimento(client: TestClient, headers, conta):
    """**A pergunta da Fila é *"o que eu preciso pagar?"*, e uma agendada já foi resolvida.**

    A conta vencia HOJE (estava no balde mais urgente depois de "atrasados") e foi agendada para
    daqui a 10 dias: ela sai do balde de vencimento — deixá-la ali pediria ao dono uma ação que ele
    já tomou — e o `hoje_cents` volta a zero.
    """
    bill = _create(client, headers, due_date=_ymd(0), amount_cents=5_000)
    antes = client.get("/payables/queue", headers=headers).json()
    assert antes["summary"]["hoje_count"] == 1

    _agendar(client, headers, bill["id"], conta, 10)

    q = client.get("/payables/queue", headers=headers).json()
    assert q["hoje"] == [] and q["summary"]["hoje_cents"] == 0
    assert q["atrasados"] == [] and q["proximos_7_dias"] == [] and q["proximos_30_dias"] == []
    assert [p["id"] for p in q["agendadas"]] == [bill["id"]]
    assert q["summary"]["agendadas_count"] == 1
    assert q["summary"]["agendadas_cents"] == 5_000


def test_a_agendada_NAO_some_da_fila(client: TestClient, headers, conta):
    """**Esconder é erro; misturar também.** A conta continua visível, num balde próprio.

    Se ela sumisse, o dono perderia de vista uma saída certa e a única tela que responde *"o que sai
    do meu caixa nos próximos dias"* passaria a mentir por omissão — que é a mesma família de
    defeito que a Onda 0 corrigiu na Projeção.
    """
    bill = _create(client, headers, due_date=_ymd(0), amount_cents=5_000)
    _agendar(client, headers, bill["id"], conta, 10)

    q = client.get("/payables/queue", headers=headers).json()
    todos = (
        q["atrasados"] + q["hoje"] + q["proximos_7_dias"] + q["proximos_30_dias"] + q["agendadas"]
    )
    assert bill["id"] in [p["id"] for p in todos], "a conta agendada SUMIU da Fila"


def test_o_balde_das_agendadas_e_calculado_NA_LEITURA(client: TestClient, headers, conta):
    """Como os outros quatro: sem job, sem cron, sem coluna. A prova é que a conta aparece no balde
    **imediatamente** depois da baixa, sem nenhuma varredura ter rodado."""
    bill = _create(client, headers, due_date=_ymd(0), amount_cents=1_234)
    _agendar(client, headers, bill["id"], conta, 3)
    q = client.get("/payables/queue", headers=headers).json()
    assert q["summary"]["agendadas_cents"] == 1_234
