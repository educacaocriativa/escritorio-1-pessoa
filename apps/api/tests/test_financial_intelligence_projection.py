"""Testes da projeção de fluxo de caixa 30/60/90 + runway (Story 5.7) — regime de CAIXA, read-only.

Cobre: saldo inicial vem da Carteira (disponível, NÃO recalculado); entradas/saídas abertas dentro
da janela entram (cumulativas), fora não; **IV2 — usa `due_date` (pagamento previsto), NUNCA
`competence_date`**, com um cenário desenhado para dar resultado DIFERENTE se o campo errado fosse
usado; recorrências futuras aparecem automaticamente (constatação da Task 2, sem lógica extra);
runway com burn positivo; runway `None` quando o caixa cresce / não há despesas (divisão por zero
tratada); janela negativa marca `alert`; e **read-only** (nenhuma escrita — IV1).

RLS/isolamento cross-tenant é validado à parte no Postgres real
(test_financial_intelligence_projection_rls.py, marcado `rls_e2e`) — aqui a suíte roda em SQLite e a
RLS não é exercida (ver conftest).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.payables.models import Payable
from app.modules.receivables.models import Charge
from app.modules.wallet.models import Transaction

REGISTER = {
    "legal_name": "Consultoria Projeção",
    "document": "22333444000181",
    "slug": "projecao",
    "email": "projecao@example.com",
    "name": "Paula",
    "password": "uma-senha-bem-grande",
}

TODAY = datetime.now(UTC).date()


def _d(days: int) -> str:
    """Data ISO de hoje + `days` (âncora UTC, a mesma que o serviço usa)."""
    return (TODAY + timedelta(days=days)).isoformat()


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _charge(client, headers, *, amount, due, competence=None) -> dict:
    body = {"kind": "service", "method": "pix", "amount_cents": amount, "due_date": due}
    if competence is not None:
        body["competence_date"] = competence
    r = client.post("/receivables/charges", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _payable(client, headers, *, amount, due, competence=None, recurrence="none", count=1) -> dict:
    body = {
        "description": "conta",
        "amount_cents": amount,
        "due_date": due,
        "recurrence": recurrence,
        "recurrence_count": count,
    }
    if competence is not None:
        body["competence_date"] = competence
    r = client.post("/payables/bills", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _seed_available(client, headers, *, gross: int) -> int:
    """Semeia saldo DISPONÍVEL na Carteira via uma venda pix (líquida imediatamente disponível).
    Retorna o líquido creditado (net = gross − split)."""
    tx = client.post(
        "/wallet/transactions",
        json={"kind": "product", "method": "pix", "gross_cents": gross},
        headers=headers,
    ).json()
    assert tx["status"] == "available"
    return tx["net_cents"]


def _projection(client, headers) -> dict:
    r = client.get("/financial-intelligence/projection", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _window(body: dict, days: int) -> dict:
    return next(w for w in body["windows"] if w["days"] == days)


def test_requires_auth(client: TestClient):
    assert client.get("/financial-intelligence/projection").status_code == 401


def test_empty_has_three_windows_and_no_runway(client: TestClient, headers):
    body = _projection(client, headers)
    assert body["saldo_inicial_cents"] == 0
    assert [w["days"] for w in body["windows"]] == [30, 60, 90]
    assert all(w["saldo_projetado_cents"] == 0 and w["alert"] is False for w in body["windows"])
    # sem despesas → sem queima → runway não se aplica (divisão por zero tratada)
    assert body["runway"]["days"] is None
    assert body["runway"]["burn_rate_cents_per_day"] == 0
    assert any("CAIXA" in n for n in body["notes"])


def test_initial_balance_comes_from_wallet_not_recalculated(client: TestClient, headers):
    net = _seed_available(client, headers, gross=150000)  # product 40% → net 90000
    body = _projection(client, headers)
    assert net == 90000
    # saldo inicial da projeção é EXATAMENTE o disponível da Carteira (reuso, não recalculado)
    assert body["saldo_inicial_cents"] == 90000


def test_inflows_and_outflows_are_cumulative_within_windows(client: TestClient, headers):
    # entrada dentro de todas as janelas (+20d)
    _charge(client, headers, amount=50000, due=_d(20))
    # saída só a partir de 60 dias (+45d)
    _payable(client, headers, amount=30000, due=_d(45))
    # fora de todas as janelas (+200d) — NÃO deve entrar
    _charge(client, headers, amount=999999, due=_d(200))

    body = _projection(client, headers)
    # cumulativo: 30d = +50000 ; 60d = +50000 −30000 = 20000 ; 90d = 20000
    assert _window(body, 30)["saldo_projetado_cents"] == 50000
    assert _window(body, 60)["saldo_projetado_cents"] == 20000
    assert _window(body, 90)["saldo_projetado_cents"] == 20000
    assert all(w["alert"] is False for w in body["windows"])


def test_empty_projection_has_zero_overdue(client: TestClient, headers):
    body = _projection(client, headers)
    assert body["overdue_inflow_cents"] == 0
    assert body["overdue_outflow_cents"] == 0
    assert not any("VENCIDOS" in n for n in body["notes"])


def test_overdue_open_items_count_as_expected_cash(client: TestClient, headers):
    """Decisão do @architect (Aria, gate da 5.7): itens VENCIDOS e ainda em aberto (atraso/
    inadimplência) ENTRAM na projeção como caixa esperado imediato — em TODAS as janelas — e a
    parcela vencida é exposta à parte. Excluí-los subestimava o caixa e (pior) ocultava contas a
    pagar já vencidas, deixando a projeção otimista demais."""
    # recebível vencido há 5 dias, ainda em aberto → esperado imediato (entra em todas as janelas)
    _charge(client, headers, amount=40000, due=_d(-5))
    # conta a pagar vencida há 3 dias, ainda em aberto → obrigação quase-certa (entra em todas)
    _payable(client, headers, amount=10000, due=_d(-3))
    # um item futuro normal, dentro de todas as janelas, para provar que soma junto ao vencido
    _charge(client, headers, amount=5000, due=_d(20))

    body = _projection(client, headers)
    # vencido líquido = 40000 − 10000 = 30000 (em todas as janelas) + 5000 futuro (em todas) = 35000
    for days in (30, 60, 90):
        assert _window(body, days)["saldo_projetado_cents"] == 35000
    # parcela vencida exposta separadamente (transparência da incerteza)
    assert body["overdue_inflow_cents"] == 40000
    assert body["overdue_outflow_cents"] == 10000
    assert any("VENCIDOS" in n for n in body["notes"])


def test_overdue_payable_shortens_runway(client: TestClient, headers):
    """Uma conta a pagar VENCIDA e em aberto é obrigação quase-certa: deve pesar no burn/runway, não
    ficar invisível (o risco que a exclusão criava — projeção otimista demais)."""
    _seed_available(client, headers, gross=150000)  # disponível 90000
    _payable(client, headers, amount=90000, due=_d(-2))  # vencida há 2 dias, ainda aberta
    body = _projection(client, headers)
    # a saída vencida entra no burn de 90d: 90000/90 = 1000/dia ; runway = 90000/1000 = 90
    assert body["runway"]["burn_rate_cents_per_day"] == 1000
    assert body["runway"]["days"] == 90
    assert body["overdue_outflow_cents"] == 90000


def test_negative_window_sets_alert(client: TestClient, headers):
    # sem saldo inicial e uma saída grande em +10d → saldo projetado negativo em todas as janelas
    _payable(client, headers, amount=100000, due=_d(10))
    body = _projection(client, headers)
    for days in (30, 60, 90):
        w = _window(body, days)
        assert w["saldo_projetado_cents"] == -100000
        assert w["alert"] is True


def test_uses_due_date_not_competence_date(client: TestClient, headers):
    """IV2 — a projeção usa `due_date` (pagamento previsto), NUNCA `competence_date`.

    Cenário desenhado para DIVERGIR: se o código usasse `competence_date` por engano, o resultado da
    janela de 30d seria 99999; usando `due_date` (correto) é 40000."""
    # A: vence dentro da janela (+10d), mas competência lá na frente (+200d) → DEVE entrar (due)
    _charge(client, headers, amount=40000, due=_d(10), competence=_d(200))
    # B: competência dentro da janela (+10d), mas vence fora (+200d) → NÃO deve entrar (due_date)
    _charge(client, headers, amount=99999, due=_d(200), competence=_d(10))

    body = _projection(client, headers)
    saldo_30 = _window(body, 30)["saldo_projetado_cents"]
    assert saldo_30 == 40000, "projeção não usou due_date (regime de caixa) — usou competência?"
    assert saldo_30 != 99999


def test_future_recurrence_occurrences_appear_without_extra_logic(client: TestClient, headers):
    """Task 2 (AC3): cada ocorrência recorrente já é uma linha própria com seu vencimento — a
    projeção as captura pela mesma query, sem reimplementar recorrência."""
    # mensal, 3x, começando em +5d → ocorrências ~ +5d, +~35d, +~65d
    created = _payable(client, headers, amount=10000, due=_d(5), recurrence="monthly", count=3)
    assert created["recurrence_count"] == 3

    body = _projection(client, headers)
    # 30d pega 1 ocorrência (−10000); 60d pega 2 (−20000); 90d pega 3 (−30000)
    assert _window(body, 30)["saldo_projetado_cents"] == -10000
    assert _window(body, 60)["saldo_projetado_cents"] == -20000
    assert _window(body, 90)["saldo_projetado_cents"] == -30000


def test_runway_with_positive_burn(client: TestClient, headers):
    _seed_available(client, headers, gross=150000)  # disponível 90000
    _payable(client, headers, amount=90000, due=_d(10))  # queima 90000 na janela de 90d
    body = _projection(client, headers)
    # burn diário = 90000 / 90 = 1000 ; runway = 90000 / 1000 = 90 dias
    assert body["runway"]["burn_rate_cents_per_day"] == 1000
    assert body["runway"]["days"] == 90


def test_runway_none_when_cash_is_growing(client: TestClient, headers):
    _seed_available(client, headers, gross=100000)  # disponível 60000
    _charge(client, headers, amount=80000, due=_d(10))  # entrada líquida → caixa cresce
    body = _projection(client, headers)
    assert body["runway"]["days"] is None
    assert body["runway"]["burn_rate_cents_per_day"] == 0
    assert any("risco" in n.lower() for n in body["notes"])


def test_runway_none_when_no_expenses(client: TestClient, headers):
    _seed_available(client, headers, gross=100000)  # disponível, sem nenhuma despesa
    body = _projection(client, headers)
    # sem burn rate → divisão por zero evitada explicitamente
    assert body["runway"]["days"] is None
    assert body["runway"]["burn_rate_cents_per_day"] == 0


def _snapshot(db: Session) -> dict:
    """Fotografia do estado que a projeção JAMAIS pode alterar (IV1 — read-only)."""
    db.expire_all()
    charges = {
        c.id: (c.status, c.amount_cents, c.due_date, c.paid_at)
        for c in db.scalars(select(Charge)).all()
    }
    payables = {
        p.id: (p.status, p.amount_cents, p.due_date, p.paid_at)
        for p in db.scalars(select(Payable)).all()
    }
    txs = {t.id: (t.status, t.net_cents) for t in db.scalars(select(Transaction)).all()}
    return {"charges": charges, "payables": payables, "transactions": txs}


def test_projection_is_read_only(client: TestClient, headers, db: Session):
    _seed_available(client, headers, gross=150000)
    _charge(client, headers, amount=50000, due=_d(20))
    _payable(client, headers, amount=30000, due=_d(45))
    before = _snapshot(db)
    _projection(client, headers)
    _projection(client, headers)
    after = _snapshot(db)
    assert after == before, "projeção escreveu/alterou dados — viola IV1 (read-only)"
