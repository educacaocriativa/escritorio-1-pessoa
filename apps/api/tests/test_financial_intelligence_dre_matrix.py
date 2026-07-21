"""Testes da DRE em matriz mensal (Story 5.11) — meses x categorias, regime de competência.

group_by="dre": mesma hierarquia grupo->categoria da DRE por período (Story 5.3), com o eixo de
mês adicionado. group_by="cost_center" é coberto em testes adicionados na Task 4 deste plano.

Porta as duas regressões de Transaction de test_financial_intelligence_dre.py (venda avulsa conta
como receita; Transaction gerada por baixa de Charge não conta em dobro) — o arquivo antigo é
removido depois que o endpoint /dre é descontinuado (Task 6).
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.wallet.models import Transaction

REGISTER = {
    "legal_name": "Consultoria Matriz",
    "document": "33444555000181",
    "slug": "matriz",
    "email": "matriz@example.com",
    "name": "Marina",
    "password": "uma-senha-bem-grande",
}


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


def _charge(client, headers, *, amount, competence, account_id=None):
    body = {
        "kind": "service", "method": "pix", "amount_cents": amount,
        "due_date": competence, "competence_date": competence,
    }
    if account_id:
        body["chart_account_id"] = account_id
    r = client.post("/receivables/charges", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _payable(client, headers, *, amount, competence, account_id=None):
    body = {
        "description": "conta", "amount_cents": amount,
        "due_date": competence, "competence_date": competence,
    }
    if account_id:
        body["chart_account_id"] = account_id
    r = client.post("/payables/bills", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _matrix(client: TestClient, headers, *, start, end, group_by="dre"):
    r = client.get(
        "/financial-intelligence/dre/matrix",
        params={"start": start, "end": end, "group_by": group_by},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _group(body: dict, key: str) -> dict:
    return next(g for g in body["groups"] if g["key"] == key)


def test_requires_auth(client: TestClient):
    r = client.get(
        "/financial-intelligence/dre/matrix", params={"start": "2026-01-01", "end": "2026-01-31"}
    )
    assert r.status_code == 401


def test_months_are_contiguous_even_without_lancamentos(client: TestClient, headers):
    body = _matrix(client, headers, start="2026-01-01", end="2026-03-31")
    assert body["months"] == ["2026-01", "2026-02", "2026-03"]
    receita = _group(body, "RECEITA")
    assert receita["rows"] == []
    assert receita["subtotal_cents"] == [0, 0, 0]
    assert body["grand_total_cents"] == [0, 0, 0]


def test_aggregates_per_month_and_category(client: TestClient, headers):
    acc = _account(client, headers, "RECEITA", "Consultoria")
    custo = _account(client, headers, "CUSTO_DIRETO", "Insumos")
    _charge(client, headers, amount=100000, competence="2026-01-10", account_id=acc)
    _charge(client, headers, amount=50000, competence="2026-01-20", account_id=acc)
    _charge(client, headers, amount=30000, competence="2026-02-05", account_id=acc)
    _payable(client, headers, amount=20000, competence="2026-02-08", account_id=custo)

    body = _matrix(client, headers, start="2026-01-01", end="2026-02-28")
    receita = _group(body, "RECEITA")
    consultoria = next(r for r in receita["rows"] if r["label"] == "Consultoria")
    assert consultoria["monthly_cents"] == [150000, 30000]
    assert consultoria["total_cents"] == 180000
    assert consultoria["kind"] == "result"
    assert receita["subtotal_cents"] == [150000, 30000]

    custo_direto = _group(body, "CUSTO_DIRETO")
    assert custo_direto["subtotal_cents"] == [0, -20000]

    assert body["grand_total_cents"] == [150000, 10000]  # 150000+0 ; 30000-20000
    assert body["grand_total"] == 160000


def test_investimento_kind_is_informational_and_excluded_from_grand_total(
    client: TestClient, headers
):
    inv = _account(client, headers, "INVESTIMENTO", "Equipamentos")
    _payable(client, headers, amount=300000, competence="2026-01-02", account_id=inv)

    body = _matrix(client, headers, start="2026-01-01", end="2026-01-31")
    investimento = _group(body, "INVESTIMENTO")
    assert investimento["rows"][0]["kind"] == "informational"
    assert investimento["subtotal_cents"] == [0]  # informativo — não entra no subtotal do grupo
    assert body["grand_total_cents"] == [0]


def test_sem_categoria_bucket_appears_only_when_present(client: TestClient, headers):
    body_empty = _matrix(client, headers, start="2026-01-01", end="2026-01-31")
    assert all(g["key"] != "SEM_CATEGORIA" for g in body_empty["groups"])

    _charge(client, headers, amount=7000, competence="2026-01-12", account_id=None)
    body = _matrix(client, headers, start="2026-01-01", end="2026-01-31")
    sem = _group(body, "SEM_CATEGORIA")
    assert sem["rows"][0]["kind"] == "uncategorized"
    assert sem["rows"][0]["monthly_cents"] == [7000]
    assert body["grand_total_cents"] == [0]  # sem categoria não entra no resultado


def test_walkin_transaction_counts_as_receita(client: TestClient, headers):
    acc = _account(client, headers, "RECEITA", "Vendas avulsas")
    r = client.post(
        "/wallet/transactions",
        json={
            "kind": "service", "method": "pix", "gross_cents": 5000,
            "chart_account_id": acc, "competence_date": "2026-01-10",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = _matrix(client, headers, start="2026-01-01", end="2026-01-31")
    receita = _group(body, "RECEITA")
    assert receita["subtotal_cents"] == [5000]


def test_paid_charge_transaction_is_not_double_counted(client: TestClient, headers, db: Session):
    acc = _account(client, headers, "RECEITA", "Consultoria paga")
    charge = _charge(client, headers, amount=20000, competence="2026-01-05", account_id=acc)
    client.post(f"/receivables/charges/{charge['id']}/pay", headers=headers)

    tx = db.execute(
        select(Transaction).where(Transaction.external_ref == charge["id"])
    ).scalar_one()
    tx.competence_date = date(2026, 1, 5)
    db.commit()

    body = _matrix(client, headers, start="2026-01-01", end="2026-01-31")
    assert _group(body, "RECEITA")["subtotal_cents"] == [20000]  # só a Charge, não em dobro


def test_end_before_start_is_422(client: TestClient, headers):
    r = client.get(
        "/financial-intelligence/dre/matrix",
        params={"start": "2026-02-01", "end": "2026-01-01"},
        headers=headers,
    )
    assert r.status_code == 422


def test_invalid_group_by_is_422(client: TestClient, headers):
    r = client.get(
        "/financial-intelligence/dre/matrix",
        params={"start": "2026-01-01", "end": "2026-01-31", "group_by": "nonsense"},
        headers=headers,
    )
    assert r.status_code == 422
