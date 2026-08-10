"""Testes do Cockpit — agregação de Agenda + CRM."""
import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Consultoria Beta",
    "document": "22333444000181",
    "slug": "beta",
    "email": "beta@example.com",
    "name": "Beto",
    "password": "uma-senha-bem-grande",
}

DAY = "2026-07-01"


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _event(**over):
    base = {
        "title": "Atendimento",
        "kind": "atendimento",
        "starts_at": f"{DAY}T10:00:00+00:00",
        "ends_at": f"{DAY}T11:00:00+00:00",
    }
    return {**base, **over}


def test_summary_empty(client: TestClient, headers):
    resp = client.get("/cockpit/summary", params={"day": DAY}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["agenda"]["today_count"] == 0
    assert body["crm"]["total_clients"] == 0
    assert body["crm"]["conversion_rate"] == 0.0
    # finance agora vem da Carteira; sem vendas, faturamento líquido é 0
    assert body["finance"]["available"] is True
    assert body["finance"]["net_revenue_cents"] == 0


def test_summary_requires_auth(client: TestClient):
    assert client.get("/cockpit/summary").status_code == 401


def test_agenda_today_count(client: TestClient, headers):
    client.post("/agenda/events", json=_event(), headers=headers)
    client.post(
        "/agenda/events",
        json=_event(starts_at=f"{DAY}T14:00:00+00:00", ends_at=f"{DAY}T15:00:00+00:00"),
        headers=headers,
    )
    # evento em outro dia não deve contar
    client.post(
        "/agenda/events",
        json=_event(starts_at="2026-08-01T10:00:00+00:00", ends_at="2026-08-01T11:00:00+00:00"),
        headers=headers,
    )
    body = client.get("/cockpit/summary", params={"day": DAY}, headers=headers).json()
    assert body["agenda"]["today_count"] == 2


def test_upcoming_critical(client: TestClient, headers):
    client.post(
        "/agenda/events",
        json=_event(title="Prazo fatal", kind="prazo", priority="critical"),
        headers=headers,
    )
    body = client.get("/cockpit/summary", params={"day": DAY}, headers=headers).json()
    crit = body["agenda"]["upcoming_critical"]
    assert len(crit) == 1
    assert crit[0]["title"] == "Prazo fatal"


def test_crm_conversion(client: TestClient, headers):
    # 4 clientes; move 1 para 'Ganho' => conversão 0.25
    ids = []
    for i in range(4):
        r = client.post("/crm/clients", json={"name": f"C{i}"}, headers=headers)
        ids.append(r.json()["id"])
    stages = client.get("/crm/stages", headers=headers).json()
    ganho = next(s for s in stages if s["is_won"])
    client.post(f"/crm/clients/{ids[0]}/move", json={"stage_id": ganho["id"]}, headers=headers)

    body = client.get("/cockpit/summary", params={"day": DAY}, headers=headers).json()
    assert body["crm"]["total_clients"] == 4
    assert body["crm"]["won_count"] == 1
    assert body["crm"]["conversion_rate"] == 0.25
    # by_stage soma ao total
    assert sum(s["count"] for s in body["crm"]["by_stage"]) == 4


def test_overdue_charges_in_cockpit(client: TestClient, headers):
    client.post(
        "/receivables/charges",
        json={
            "kind": "service",
            "method": "pix",
            "amount_cents": 12000,
            "due_date": "2020-01-01",
            "description": "Mensalidade atrasada",
        },
        headers=headers,
    )
    body = client.get("/cockpit/summary", params={"day": DAY}, headers=headers).json()
    assert len(body["overdue"]) == 1
    assert body["overdue"][0]["amount_cents"] == 12000
    assert body["overdue"][0]["charge_id"]


def test_default_day_is_today(client: TestClient, headers):
    # sem 'day' não deve quebrar (usa hoje em UTC)
    resp = client.get("/cockpit/summary", headers=headers)
    assert resp.status_code == 200


def test_invalid_day_returns_422(client: TestClient, headers):
    resp = client.get("/cockpit/summary", params={"day": "abc"}, headers=headers)
    assert resp.status_code == 422


def test_cancelled_event_not_counted(client: TestClient, headers):
    created = client.post("/agenda/events", json=_event(), headers=headers).json()["event"]
    client.post(f"/agenda/events/{created['id']}/cancel", headers=headers)
    body = client.get("/cockpit/summary", params={"day": DAY}, headers=headers).json()
    assert body["agenda"]["today_count"] == 0  # cancelado não conta


def test_event_near_local_midnight_counts_on_local_day(client: TestClient, headers):
    # Story 4.5 (Task 5): janela do dia ancorada no fuso do tenant (America/Sao_Paulo, UTC-3).
    # Um evento às 23:30 LOCAL do dia 2026-07-01 = 2026-07-02T02:30Z. Com a janela ANTIGA em UTC
    # ([D00:00Z, D+1 00:00Z)) ele caía fora e SUMIA do resumo do dia local (bug do CLAUDE.md).
    # Com a janela no fuso ([D03:00Z, D+1 03:00Z)) ele aparece no dia local correto.
    client.post(
        "/agenda/events",
        json=_event(
            title="Atendimento noturno",
            starts_at="2026-07-02T02:30:00+00:00",  # 23:30 local de 2026-07-01
            ends_at="2026-07-02T03:00:00+00:00",
        ),
        headers=headers,
    )
    body = client.get("/cockpit/summary", params={"day": DAY}, headers=headers).json()
    assert body["agenda"]["today_count"] == 1
    titles = [e["title"] for e in body["agenda"]["today_events"]]
    assert "Atendimento noturno" in titles


def test_done_critical_not_in_alert(client: TestClient, headers):
    created = client.post(
        "/agenda/events",
        json=_event(title="Prazo cumprido", kind="prazo", priority="critical"),
        headers=headers,
    ).json()["event"]
    # marca como concluído
    client.patch(f"/agenda/events/{created['id']}", json={"status": "done"}, headers=headers)
    body = client.get("/cockpit/summary", params={"day": DAY}, headers=headers).json()
    assert body["agenda"]["upcoming_critical"] == []  # prazo cumprido sai do alerta


# ── Onda 3 — o Cockpit mostra os DOIS planos, lado a lado e nunca somados ─────────────────────


def _conta(client, headers, **over):
    payload = {
        "name": "Itaú PJ",
        "kind": "checking",
        "opening_balance_cents": 700_00,
        "opening_balance_is_known": True,
        "opening_date": "2026-01-01",
    }
    payload.update(over)
    resp = client.post("/bank/accounts", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_cockpit_expoe_saldo_em_conta_com_procedencia(client: TestClient, headers):
    """§1.3c: todo campo de SALDO declara de qual plano vem.

    ⚠️ **`net_revenue_cents` NÃO ganha `_origem`**, e a ausência é correta: ele é FATURAMENTO, não
    saldo — o design-mãe §6.5 diz explicitamente que aquele número está certo e não muda. Pendurar
    procedência nele aplicaria a regra fora do alvo e viraria ritual.
    """
    _conta(client, headers)

    finance = client.get("/cockpit/summary", headers=headers).json()["finance"]
    assert finance["saldo_em_conta_cents"] == 700_00
    assert finance["saldo_em_conta_origem"] == "banco"
    assert "net_revenue_origem" not in finance


def test_sem_conta_o_saldo_em_conta_e_none_e_nao_zero(client: TestClient, headers):
    """`None` ≠ zero. Zero afirmaria *"você não tem nada no banco"* — falso, e indistinguível de um
    saldo genuinamente zerado. Mesmo princípio do principal `None` da Onda 2b-ii."""
    finance = client.get("/cockpit/summary", headers=headers).json()["finance"]
    assert finance["saldo_em_conta_cents"] is None
    assert finance["saldo_em_conta_origem"] == "indisponivel"


def test_saldo_de_abertura_desconhecido_derruba_a_procedencia(client: TestClient, headers):
    """Story 8.21: o NÚMERO continua existindo; quem diz "não sei" é a procedência.

    Basta UMA conta sem saldo de abertura declarado para o total deixar de ser afirmável — o total
    não é mais confiável que a sua parcela mais frágil.
    """
    _conta(client, headers, opening_balance_cents=0, opening_balance_is_known=False)

    finance = client.get("/cockpit/summary", headers=headers).json()["finance"]
    assert finance["saldo_em_conta_cents"] == 0  # o número existe
    assert finance["saldo_em_conta_origem"] == "indisponivel"  # a afirmação é suprimida
