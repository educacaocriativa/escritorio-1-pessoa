"""Testes da DRE por categoria (Story 5.3) — agregação read-only em regime de competência.

Cobre: soma correta por grupo/categoria num período; lançamento fora do período não entra;
lançamento sem `chart_account_id` cai no bucket "sem categoria" sem quebrar o resultado; o
resultado bate com a fórmula (Receita − Custos − Despesas − Tributos ± Financeiro) com valores
conhecidos; INVESTIMENTO fora do resultado; e **read-only** (nenhuma linha de charges/payables/
chart_accounts muda ao gerar o relatório — IV1).

RLS/isolamento cross-tenant é validado à parte no Postgres real
(test_financial_intelligence_dre_rls.py, marcado `rls_e2e`) — aqui a suíte roda em SQLite e a RLS
não é exercida (ver conftest).
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.chart_of_accounts.models import ChartAccount
from app.modules.payables.models import Payable
from app.modules.receivables.models import Charge
from app.modules.wallet.models import Transaction

REGISTER = {
    "legal_name": "Consultoria DRE",
    "document": "22333444000181",
    "slug": "dre",
    "email": "dre@example.com",
    "name": "Denise",
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


def _charge(client, headers, *, amount, competence, account_id=None, kind="service"):
    body = {
        "kind": kind,
        "method": "pix",
        "amount_cents": amount,
        "due_date": competence,
        "competence_date": competence,
    }
    if account_id:
        body["chart_account_id"] = account_id
    r = client.post("/receivables/charges", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _payable(client, headers, *, amount, competence, account_id=None):
    body = {
        "description": "conta",
        "amount_cents": amount,
        "due_date": competence,
        "competence_date": competence,
    }
    if account_id:
        body["chart_account_id"] = account_id
    r = client.post("/payables/bills", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _seed_scenario(client: TestClient, headers) -> dict[str, str]:
    """Cenário com valores conhecidos. Retorna o mapa de ids de conta (para asserts finos)."""
    acc = {
        "consult": _account(client, headers, "RECEITA", "Consultoria"),
        "mentoria": _account(client, headers, "RECEITA", "Mentoria"),
        "custo": _account(client, headers, "CUSTO_DIRETO", "Insumos"),
        "desp": _account(client, headers, "DESPESA_FIXA", "Aluguel"),
        "trib": _account(client, headers, "TRIBUTOS", "ISS"),
        "rend": _account(client, headers, "FINANCEIRO", "Rendimento"),
        "tarifa": _account(client, headers, "FINANCEIRO", "Tarifas"),
        "inv": _account(client, headers, "INVESTIMENTO", "Equipamentos"),
    }
    # Receitas (Charges, sinal +)
    _charge(client, headers, amount=100000, competence="2026-07-10", account_id=acc["consult"])
    _charge(client, headers, amount=50000, competence="2026-07-20", account_id=acc["consult"])
    _charge(client, headers, amount=30000, competence="2026-07-15", account_id=acc["mentoria"])
    _charge(client, headers, amount=2000, competence="2026-07-05", account_id=acc["rend"])
    # Fora do período (competência em agosto) — NÃO deve entrar
    _charge(client, headers, amount=999999, competence="2026-08-05", account_id=acc["consult"])
    # Receita sem categoria
    _charge(client, headers, amount=7000, competence="2026-07-12", account_id=None)
    # Despesas/custos/tributos/financeiro/investimento (Payables, sinal −)
    _payable(client, headers, amount=20000, competence="2026-07-08", account_id=acc["custo"])
    _payable(client, headers, amount=40000, competence="2026-07-01", account_id=acc["desp"])
    _payable(client, headers, amount=10000, competence="2026-07-25", account_id=acc["trib"])
    _payable(client, headers, amount=500, competence="2026-07-03", account_id=acc["tarifa"])
    _payable(client, headers, amount=300000, competence="2026-07-02", account_id=acc["inv"])
    # Despesa sem categoria
    _payable(client, headers, amount=3000, competence="2026-07-18", account_id=None)
    return acc


def _dre(client: TestClient, headers, *, start=START, end=END):
    r = client.get(
        "/financial-intelligence/dre", params={"start": start, "end": end}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


def _group(body: dict, grupo: str) -> dict:
    return next(g for g in body["groups"] if g["grupo_dre"] == grupo)


def test_requires_auth(client: TestClient):
    r = client.get("/financial-intelligence/dre", params={"start": START, "end": END})
    assert r.status_code == 401


def test_empty_period_has_all_groups_zero(client: TestClient, headers):
    body = _dre(client, headers)
    # sempre os 6 grupos na ordem canônica, mesmo sem lançamento
    assert [g["grupo_dre"] for g in body["groups"]] == [
        "RECEITA", "CUSTO_DIRETO", "DESPESA_FIXA", "TRIBUTOS", "FINANCEIRO", "INVESTIMENTO",
    ]
    assert all(g["total_cents"] == 0 and g["categorias"] == [] for g in body["groups"])
    assert body["resultado_cents"] == 0
    assert body["sem_categoria"]["total_cents"] == 0
    assert body["sem_categoria"]["categorias"] == []


def test_aggregation_by_group_and_category(client: TestClient, headers):
    _seed_scenario(client, headers)
    body = _dre(client, headers)

    receita = _group(body, "RECEITA")
    assert receita["total_cents"] == 180000
    cats = {c["categoria"]: c for c in receita["categorias"]}
    # duas cobranças na mesma categoria somam e contam 2
    assert cats["Consultoria"]["amount_cents"] == 150000
    assert cats["Consultoria"]["count"] == 2
    assert cats["Mentoria"]["amount_cents"] == 30000

    assert _group(body, "CUSTO_DIRETO")["total_cents"] == -20000
    assert _group(body, "DESPESA_FIXA")["total_cents"] == -40000
    assert _group(body, "TRIBUTOS")["total_cents"] == -10000
    # FINANCEIRO mistura sinal (rendimento + / tarifa −): 2000 − 500 = 1500
    assert _group(body, "FINANCEIRO")["total_cents"] == 1500


def test_out_of_period_excluded(client: TestClient, headers):
    _seed_scenario(client, headers)
    body = _dre(client, headers)
    # a cobrança de 999999 (competência em agosto) não infla a Consultoria
    consult = next(
        c for c in _group(body, "RECEITA")["categorias"] if c["categoria"] == "Consultoria"
    )
    assert consult["amount_cents"] == 150000


def test_sem_categoria_bucket_does_not_break_result(client: TestClient, headers):
    _seed_scenario(client, headers)
    body = _dre(client, headers)
    # +7000 (receber) e −3000 (pagar) sem categoria => net +4000, 2 lançamentos
    assert body["sem_categoria"]["total_cents"] == 4000
    assert body["sem_categoria"]["categorias"][0]["count"] == 2
    # sem categoria NÃO entra no resultado
    assert body["resultado_cents"] == 111500


def test_result_matches_formula_and_excludes_investimento(client: TestClient, headers):
    _seed_scenario(client, headers)
    body = _dre(client, headers)
    # Receita − Custos − Despesas − Tributos ± Financeiro (INVESTIMENTO e sem-categoria fora)
    # 180000 − 20000 − 40000 − 10000 + 1500 = 111500
    assert body["resultado_cents"] == 111500
    # INVESTIMENTO existe no relatório, mas fora do resultado
    assert _group(body, "INVESTIMENTO")["total_cents"] == -300000
    assert any("INVESTIMENTO" in n for n in body["notes"])


def test_end_before_start_is_422(client: TestClient, headers):
    r = client.get(
        "/financial-intelligence/dre",
        params={"start": END, "end": START},
        headers=headers,
    )
    assert r.status_code == 422


def test_missing_params_is_422(client: TestClient, headers):
    assert client.get("/financial-intelligence/dre", headers=headers).status_code == 422


def _snapshot(db: Session) -> dict:
    """Fotografia primitiva do estado que a DRE JAMAIS pode alterar (IV1)."""
    db.expire_all()
    charges = {
        c.id: (c.status, c.amount_cents, c.competence_date, c.paid_at, c.chart_account_id)
        for c in db.scalars(select(Charge)).all()
    }
    payables = {
        p.id: (p.status, p.amount_cents, p.competence_date, p.paid_at, p.chart_account_id)
        for p in db.scalars(select(Payable)).all()
    }
    accounts = {
        a.id: (a.grupo_dre, a.categoria, a.archived_at)
        for a in db.scalars(select(ChartAccount)).all()
    }
    return {"charges": charges, "payables": payables, "accounts": accounts}


def test_report_is_read_only(client: TestClient, headers, db: Session):
    _seed_scenario(client, headers)
    before = _snapshot(db)
    # gera o relatório duas vezes — não pode ter efeito colateral de escrita
    _dre(client, headers)
    _dre(client, headers)
    after = _snapshot(db)
    assert after == before, "DRE escreveu/alterou dados — viola IV1 (read-only)"


# ── Story 5.10: Carteira (Transaction) entra na DRE ─────────────────────────────────────────────


def test_walkin_transaction_counts_as_receita(client: TestClient, headers):
    """Venda avulsa ("Registrar venda", sem Charge por trás) classificada entra na DRE como
    receita — antes da Story 5.10 a Carteira ficava totalmente fora do relatório."""
    acc = _account(client, headers, "RECEITA", "Vendas avulsas")
    r = client.post(
        "/wallet/transactions",
        json={
            "kind": "service", "method": "pix", "gross_cents": 5000,
            "chart_account_id": acc, "competence_date": "2026-07-10",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = _dre(client, headers)
    receita = _group(body, "RECEITA")
    assert receita["total_cents"] == 5000
    assert receita["categorias"][0]["categoria"] == "Vendas avulsas"


def test_paid_charge_transaction_is_not_double_counted(
    client: TestClient, headers, db: Session
):
    """A Transaction gerada ao pagar uma Charge (`external_ref=charge.id`) NÃO soma de novo na
    DRE — a Charge já é contada; somar as duas dobraria a receita do período."""
    acc = _account(client, headers, "RECEITA", "Consultoria paga")
    charge = _charge(client, headers, amount=20000, competence="2026-07-05", account_id=acc)
    client.post(f"/receivables/charges/{charge['id']}/pay", headers=headers)

    # Força a competência da Transaction resultante PRA DENTRO da janela testada — assim, se o
    # filtro `external_ref IS NULL` da DRE quebrar, o teste pega o dobro (40000), não um falso
    # negativo por a transação cair fora do período por coincidência de data.
    tx = db.execute(
        select(Transaction).where(Transaction.external_ref == charge["id"])
    ).scalar_one()
    tx.competence_date = date(2026, 7, 5)
    db.commit()

    body = _dre(client, headers)
    receita = _group(body, "RECEITA")
    assert receita["total_cents"] == 20000  # só a Charge — a Transaction fica de fora
