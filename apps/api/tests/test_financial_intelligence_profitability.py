"""Testes de lucratividade por contrato (Story 5.4) — DRE do contrato, margem de contribuição,
break-even e rateio de overhead. Agregação read-only em regime de competência.

Cobre (Tasks 3-6 / AC1-3 / IV1-3):
- vincular lançamento a contrato via `contract_id`; lançamento sem contrato = bucket "Empresa"
  (não aparece na DRE de nenhum contrato específico);
- margem de contribuição correta (R$ e %) usando o SINAL canônico (Receber=+, Pagar=−; margem =
  SOMA de totais assinados, nunca `receita − custo`);
- break-even correto com custo fixo atribuído; margem negativa → break-even "não atingível" sem 500;
- rateio de overhead muda o resultado retornado mas NÃO altera nenhuma linha em
  payables/charges/contracts (assert antes/depois — IV2);
- divisão por zero (contrato sem receita) não quebra (retorna 200, pct None).

RLS/isolamento cross-tenant é validado à parte no Postgres real
(test_financial_intelligence_profitability_rls.py, `rls_e2e`) — aqui a suíte roda em SQLite.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.contracts.models import Contract
from app.modules.payables.models import Payable
from app.modules.receivables.models import Charge

REGISTER = {
    "legal_name": "Consultoria Lucro",
    "document": "10101010000177",
    "slug": "lucro",
    "email": "lucro@example.com",
    "name": "Lara",
    "password": "uma-senha-bem-grande",
}

START = "2026-07-01"
END = "2026-07-31"


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _account(client: TestClient, headers, grupo: str, categoria: str) -> str:
    r = client.post(
        "/chart-of-accounts", json={"grupo_dre": grupo, "categoria": categoria}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _contract(client: TestClient, headers, *, title="Projeto A", fixed_costs=None) -> dict:
    body = {"title": title, "clauses": [{"title": "Objeto", "text": "Serviços."}]}
    r = client.post("/contracts", json=body, headers=headers)
    assert r.status_code == 201, r.text
    c = r.json()
    if fixed_costs is not None:
        r2 = client.patch(
            f"/contracts/{c['id']}",
            json={"fixed_costs_allocated_cents": fixed_costs},
            headers=headers,
        )
        assert r2.status_code == 200, r2.text
        c = r2.json()
    return c


def _charge(client, headers, *, amount, competence, account_id=None, contract_id=None):
    body = {
        "kind": "service",
        "method": "pix",
        "amount_cents": amount,
        "due_date": competence,
        "competence_date": competence,
    }
    if account_id:
        body["chart_account_id"] = account_id
    if contract_id:
        body["contract_id"] = contract_id
    r = client.post("/receivables/charges", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _payable(client, headers, *, amount, competence, account_id=None, contract_id=None):
    body = {
        "description": "conta",
        "amount_cents": amount,
        "due_date": competence,
        "competence_date": competence,
    }
    if account_id:
        body["chart_account_id"] = account_id
    if contract_id:
        body["contract_id"] = contract_id
    r = client.post("/payables/bills", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _dre(client, headers, contract_id, *, start=START, end=END, include_overhead=False):
    r = client.get(
        f"/financial-intelligence/contracts/{contract_id}/dre",
        params={"start": start, "end": end, "include_overhead": include_overhead},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


# ── Auth / validação de parâmetros ──────────────────────────────────────────
def test_requires_auth(client: TestClient):
    r = client.get(
        "/financial-intelligence/contracts/qualquer/dre", params={"start": START, "end": END}
    )
    assert r.status_code == 401


def test_contract_not_found_is_404(client: TestClient, headers):
    r = client.get(
        "/financial-intelligence/contracts/inexistente/dre",
        params={"start": START, "end": END},
        headers=headers,
    )
    assert r.status_code == 404


def test_end_before_start_is_422(client: TestClient, headers):
    c = _contract(client, headers)
    r = client.get(
        f"/financial-intelligence/contracts/{c['id']}/dre",
        params={"start": END, "end": START},
        headers=headers,
    )
    assert r.status_code == 422


# ── Margem de contribuição (R$ e %) ─────────────────────────────────────────
def test_margin_and_result_and_break_even(client: TestClient, headers):
    receita = _account(client, headers, "RECEITA", "Consultoria")
    custo = _account(client, headers, "CUSTO_DIRETO", "Insumos")
    c = _contract(client, headers, fixed_costs=30000)

    _charge(client, headers, amount=100000, competence="2026-07-10",
            account_id=receita, contract_id=c["id"])
    _payable(client, headers, amount=40000, competence="2026-07-12",
             account_id=custo, contract_id=c["id"])

    body = _dre(client, headers, c["id"])
    # Receita +100000; Custo Direto já assinado −40000; margem = SOMA = 60000 (não 140000!)
    assert body["receita_cents"] == 100000
    assert body["custo_direto_cents"] == -40000
    assert body["margem_contribuicao_cents"] == 60000
    assert body["margem_contribuicao_pct"] == pytest.approx(0.6)
    # resultado = margem − custo fixo atribuído − overhead(0) = 60000 − 30000 = 30000
    assert body["fixed_costs_allocated_cents"] == 30000
    assert body["overhead_allocated_cents"] == 0
    assert body["resultado_cents"] == 30000
    # break-even = custo fixo / margem% = 30000 / 0.6 = 50000 (receita p/ empatar)
    assert body["break_even_reachable"] is True
    assert body["break_even_cents"] == 50000
    # detalhamento por categoria (drill)
    cats = {x["categoria"]: x for x in body["receita"]["categorias"]}
    assert cats["Consultoria"]["amount_cents"] == 100000


def test_other_result_groups_hit_result_not_margin(client: TestClient, headers):
    """REGRA CANÔNICA (Aria, 5.4): um custo atribuído ao contrato em grupo ALÉM da margem
    (Despesa Fixa/Tributos/Financeiro) NÃO entra na margem de contribuição, mas COMPÕE o
    resultado — jamais some, virando só nota. Precedente para a 5.8 (margem ≠ resultado)."""
    receita = _account(client, headers, "RECEITA", "Consultoria")
    custo = _account(client, headers, "CUSTO_DIRETO", "Insumos")
    despesa = _account(client, headers, "DESPESA_FIXA", "Taxa mensal do projeto")
    c = _contract(client, headers)  # sem custo fixo manual

    _charge(client, headers, amount=100000, competence="2026-07-10",
            account_id=receita, contract_id=c["id"])
    _payable(client, headers, amount=40000, competence="2026-07-12",
             account_id=custo, contract_id=c["id"])
    # taxa fixa mensal do projeto, atribuída ao contrato (o cenário do footgun da missão)
    _payable(client, headers, amount=10000, competence="2026-07-15",
             account_id=despesa, contract_id=c["id"])

    body = _dre(client, headers, c["id"])
    # margem NÃO muda: só Receita (+100000) + Custo Direto (−40000) = 60000
    assert body["margem_contribuicao_cents"] == 60000
    assert body["margem_contribuicao_pct"] == pytest.approx(0.6)
    # a despesa fixa atribuída entra em outros_resultado (assinada, negativa)
    assert body["outros_resultado_cents"] == -10000
    # resultado = margem(60000) + outros(−10000) − custo fixo(0) − overhead(0) = 50000
    assert body["resultado_cents"] == 50000
    # a existência de outros grupos é sinalizada (não descartada em silêncio)
    assert any("outros grupos" in n.lower() for n in body["notes"])


def test_investment_excluded_from_result(client: TestClient, headers):
    """INVESTIMENTO atribuído ao contrato fica FORA do resultado (movimento de balanço, não DRE —
    mesma exclusão da 5.3), apenas notado."""
    receita = _account(client, headers, "RECEITA", "Consultoria")
    invest = _account(client, headers, "INVESTIMENTO", "Equipamento")
    c = _contract(client, headers)
    _charge(client, headers, amount=100000, competence="2026-07-10",
            account_id=receita, contract_id=c["id"])
    _payable(client, headers, amount=50000, competence="2026-07-12",
             account_id=invest, contract_id=c["id"])
    body = _dre(client, headers, c["id"])
    # investimento não entra na margem NEM no resultado
    assert body["margem_contribuicao_cents"] == 100000
    assert body["outros_resultado_cents"] == 0
    assert body["resultado_cents"] == 100000
    assert any("investimento" in n.lower() for n in body["notes"])


def test_empresa_bucket_excluded_from_contract_dre(client: TestClient, headers):
    """Lançamento SEM contract_id (bucket 'Empresa') não entra na DRE de um contrato específico."""
    receita = _account(client, headers, "RECEITA", "Consultoria")
    c = _contract(client, headers)
    _charge(client, headers, amount=100000, competence="2026-07-10",
            account_id=receita, contract_id=c["id"])
    # receita "da empresa" (sem contrato) — NÃO deve inflar a DRE do contrato
    _charge(client, headers, amount=999999, competence="2026-07-11", account_id=receita)

    body = _dre(client, headers, c["id"])
    assert body["receita_cents"] == 100000


def test_out_of_period_excluded(client: TestClient, headers):
    receita = _account(client, headers, "RECEITA", "Consultoria")
    c = _contract(client, headers)
    _charge(client, headers, amount=100000, competence="2026-07-10",
            account_id=receita, contract_id=c["id"])
    _charge(client, headers, amount=999999, competence="2026-08-10",
            account_id=receita, contract_id=c["id"])
    body = _dre(client, headers, c["id"])
    assert body["receita_cents"] == 100000


# ── Break-even não atingível / divisão por zero ─────────────────────────────
def test_negative_margin_break_even_not_reachable(client: TestClient, headers):
    receita = _account(client, headers, "RECEITA", "Consultoria")
    custo = _account(client, headers, "CUSTO_DIRETO", "Insumos")
    c = _contract(client, headers, fixed_costs=10000)
    _charge(client, headers, amount=50000, competence="2026-07-10",
            account_id=receita, contract_id=c["id"])
    _payable(client, headers, amount=80000, competence="2026-07-12",
             account_id=custo, contract_id=c["id"])
    body = _dre(client, headers, c["id"])
    # margem = 50000 + (−80000) = −30000; % = −0.6
    assert body["margem_contribuicao_cents"] == -30000
    assert body["margem_contribuicao_pct"] == pytest.approx(-0.6)
    # margem <= 0 e há custo fixo → break-even NÃO atingível (estado explícito, sem 500)
    assert body["break_even_reachable"] is False
    assert body["break_even_cents"] is None
    assert any("break-even" in n.lower() for n in body["notes"])


def test_no_revenue_does_not_crash(client: TestClient, headers):
    """Contrato sem receita no período: pct None (proteção div/0), 200 — nunca ZeroDivisionError."""
    custo = _account(client, headers, "CUSTO_DIRETO", "Insumos")
    c = _contract(client, headers, fixed_costs=5000)
    _payable(client, headers, amount=20000, competence="2026-07-12",
             account_id=custo, contract_id=c["id"])
    body = _dre(client, headers, c["id"])
    assert body["receita_cents"] == 0
    assert body["margem_contribuicao_pct"] is None
    assert body["break_even_reachable"] is False
    assert body["break_even_cents"] is None
    # resultado = margem(−20000) − custo fixo(5000) − 0 = −25000
    assert body["resultado_cents"] == -25000


def test_zero_fixed_cost_break_even_is_zero(client: TestClient, headers):
    receita = _account(client, headers, "RECEITA", "Consultoria")
    c = _contract(client, headers)  # sem custo fixo → break-even trivial em 0
    _charge(client, headers, amount=100000, competence="2026-07-10",
            account_id=receita, contract_id=c["id"])
    body = _dre(client, headers, c["id"])
    assert body["break_even_reachable"] is True
    assert body["break_even_cents"] == 0


# ── Rateio de overhead (AC3 / IV2) ──────────────────────────────────────────
def _seed_overhead_scenario(client, headers):
    receita = _account(client, headers, "RECEITA", "Consultoria")
    despesa = _account(client, headers, "DESPESA_FIXA", "Aluguel")
    a = _contract(client, headers, title="Projeto A", fixed_costs=30000)
    b = _contract(client, headers, title="Projeto B")
    # receita por contrato: A=100000, B=100000 → total 200000, proporção de A = 0.5
    _charge(client, headers, amount=100000, competence="2026-07-10",
            account_id=receita, contract_id=a["id"])
    _charge(client, headers, amount=100000, competence="2026-07-10",
            account_id=receita, contract_id=b["id"])
    # overhead da empresa (sem contrato): DESPESA_FIXA 20000
    _payable(client, headers, amount=20000, competence="2026-07-05", account_id=despesa)
    return a, b


def test_overhead_default_off(client: TestClient, headers):
    a, _b = _seed_overhead_scenario(client, headers)
    body = _dre(client, headers, a["id"])  # include_overhead default false
    assert body["overhead_allocated_cents"] == 0
    # resultado sem overhead = margem(100000) − custo fixo(30000) = 70000
    assert body["resultado_cents"] == 70000


def test_overhead_allocated_when_requested(client: TestClient, headers):
    a, _b = _seed_overhead_scenario(client, headers)
    body = _dre(client, headers, a["id"], include_overhead=True)
    # overhead pool 20000 * proporção 0.5 = 10000
    assert body["overhead_allocated_cents"] == 10000
    # resultado = margem(100000) − custo fixo(30000) − overhead(10000) = 60000
    assert body["resultado_cents"] == 60000
    assert any("overhead" in n.lower() for n in body["notes"])


def _snapshot(db: Session) -> dict:
    """Fotografia primitiva do estado que o rateio JAMAIS pode alterar (IV2)."""
    db.expire_all()
    charges = {
        c.id: (c.status, c.amount_cents, c.contract_id) for c in db.scalars(select(Charge)).all()
    }
    payables = {
        p.id: (p.status, p.amount_cents, p.contract_id) for p in db.scalars(select(Payable)).all()
    }
    contracts = {
        c.id: (c.status, c.fixed_costs_allocated_cents) for c in db.scalars(select(Contract)).all()
    }
    return {"charges": charges, "payables": payables, "contracts": contracts}


def test_overhead_allocation_is_read_only(client: TestClient, headers, db: Session):
    a, _b = _seed_overhead_scenario(client, headers)
    before = _snapshot(db)
    # gera a DRE com rateio duas vezes — não pode escrever em payables/charges/contracts
    _dre(client, headers, a["id"], include_overhead=True)
    _dre(client, headers, a["id"], include_overhead=True)
    after = _snapshot(db)
    assert after == before, "rateio de overhead escreveu/alterou dados — viola IV2 (read-only)"


# ── Vínculo aditivo / desvínculo (AC1) ──────────────────────────────────────
def test_relink_and_unlink_contract(client: TestClient, headers):
    receita = _account(client, headers, "RECEITA", "Consultoria")
    c = _contract(client, headers)
    ch = _charge(client, headers, amount=100000, competence="2026-07-10", account_id=receita)
    # sem contrato ainda → não entra na DRE do contrato
    assert _dre(client, headers, c["id"])["receita_cents"] == 0
    # vincula
    r = client.patch(
        f"/receivables/charges/{ch['id']}", json={"contract_id": c["id"]}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["contract_id"] == c["id"]
    assert _dre(client, headers, c["id"])["receita_cents"] == 100000
    # desvincula ("" → bucket Empresa)
    r2 = client.patch(
        f"/receivables/charges/{ch['id']}", json={"contract_id": ""}, headers=headers
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["contract_id"] is None
    assert _dre(client, headers, c["id"])["receita_cents"] == 0


def test_link_to_missing_contract_is_404(client: TestClient, headers):
    r = client.post(
        "/receivables/charges",
        json={
            "kind": "service", "method": "pix", "amount_cents": 1000,
            "due_date": "2026-07-10", "contract_id": "nao-existe",
        },
        headers=headers,
    )
    assert r.status_code == 404
