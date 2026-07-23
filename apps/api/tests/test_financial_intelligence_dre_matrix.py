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


def _cost_center(client, headers, *, name, kind="area"):
    r = client.post("/cost-centers", json={"name": name, "kind": kind}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_cost_center_grouping_splits_by_center_and_category(client: TestClient, headers):
    tecnica = _cost_center(client, headers, name="Tecnica")
    comercial = _cost_center(client, headers, name="Comercial")
    curso_acc = _account(client, headers, "DESPESA_FIXA", "Curso")

    def _payable_cc(amount, competence, cc_id, account_id):
        body = {
            "description": "conta", "amount_cents": amount,
            "due_date": competence, "competence_date": competence,
            "chart_account_id": account_id, "cost_center_id": cc_id,
        }
        r = client.post("/payables/bills", json=body, headers=headers)
        assert r.status_code == 201, r.text
        return r.json()

    _payable_cc(500000, "2026-01-10", tecnica, curso_acc)
    _payable_cc(200000, "2026-02-05", comercial, curso_acc)

    body = _matrix(client, headers, start="2026-01-01", end="2026-02-28", group_by="cost_center")
    tecnica_group = _group(body, tecnica)
    assert tecnica_group["label"] == "Tecnica"
    curso_row = next(r for r in tecnica_group["rows"] if r["label"] == "Curso")
    assert curso_row["monthly_cents"] == [-500000, 0]
    assert curso_row["kind"] == "result"

    comercial_group = _group(body, comercial)
    assert comercial_group["subtotal_cents"] == [0, -200000]


def test_cost_center_grouping_includes_unassigned_bucket(client: TestClient, headers):
    acc = _account(client, headers, "DESPESA_FIXA", "Aluguel")
    _payable(client, headers, amount=40000, competence="2026-01-01", account_id=acc)

    body = _matrix(client, headers, start="2026-01-01", end="2026-01-31", group_by="cost_center")
    unassigned = _group(body, "_unassigned")
    assert unassigned["label"] == "Não atribuído"
    assert unassigned["subtotal_cents"] == [-40000]


def test_cost_center_grouping_mixes_kinds_within_one_center(client: TestClient, headers):
    """Um único centro de custo pode ter uma categoria de RECEITA e uma de INVESTIMENTO —
    o subtotal do grupo soma só a linha kind='result', mesmo com as duas dentro do MESMO grupo
    (a razão de `kind` ter virado propriedade da LINHA, não do grupo — ver docstring)."""
    cc = _cost_center(client, headers, name="Sócio A")
    receita_acc = _account(client, headers, "RECEITA", "Consultoria")
    inv_acc = _account(client, headers, "INVESTIMENTO", "Equipamentos")

    r = client.post(
        "/receivables/charges",
        json={
            "kind": "service", "method": "pix", "amount_cents": 100000,
            "due_date": "2026-01-05", "competence_date": "2026-01-05",
            "chart_account_id": receita_acc, "cost_center_id": cc,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    client.post(
        "/payables/bills",
        json={
            "description": "notebook", "amount_cents": 300000,
            "due_date": "2026-01-06", "competence_date": "2026-01-06",
            "chart_account_id": inv_acc, "cost_center_id": cc,
        },
        headers=headers,
    )

    body = _matrix(client, headers, start="2026-01-01", end="2026-01-31", group_by="cost_center")
    group = _group(body, cc)
    kinds = {r["label"]: r["kind"] for r in group["rows"]}
    assert kinds == {"Consultoria": "result", "Equipamentos": "informational"}
    assert group["subtotal_cents"] == [100000]  # só a Consultoria — o investimento é informativo


def test_cost_center_grouping_keeps_same_categoria_name_across_different_groups_separate(
    client: TestClient, headers
):
    """Duas contas com o MESMO nome de categoria em grupos DRE DIFERENTES, sob o MESMO centro de
    custo, não podem se fundir numa linha só (bug encontrado na revisão da Task 4: categoria é
    única só DENTRO do grupo, nunca por tenant inteiro)."""
    cc = _cost_center(client, headers, name="Sócio B")
    inv_acc = _account(client, headers, "INVESTIMENTO", "Equipamentos")
    # MESMO nome, grupo diferente
    custo_acc = _account(client, headers, "CUSTO_DIRETO", "Equipamentos")

    r1 = client.post(
        "/payables/bills",
        json={
            "description": "notebook", "amount_cents": 300000,
            "due_date": "2026-01-06", "competence_date": "2026-01-06",
            "chart_account_id": inv_acc, "cost_center_id": cc,
        },
        headers=headers,
    )
    assert r1.status_code == 201, r1.text
    r2 = client.post(
        "/payables/bills",
        json={
            "description": "manutenção", "amount_cents": 5000,
            "due_date": "2026-01-07", "competence_date": "2026-01-07",
            "chart_account_id": custo_acc, "cost_center_id": cc,
        },
        headers=headers,
    )
    assert r2.status_code == 201, r2.text

    body = _matrix(client, headers, start="2026-01-01", end="2026-01-31", group_by="cost_center")
    group = _group(body, cc)
    equipamentos_rows = [r for r in group["rows"] if r["label"] == "Equipamentos"]
    assert len(equipamentos_rows) == 2, "as duas contas 'Equipamentos' foram fundidas numa só linha"
    kinds = {r["kind"] for r in equipamentos_rows}
    assert kinds == {"informational", "result"}
    amounts = sorted(r["monthly_cents"][0] for r in equipamentos_rows)
    assert amounts == [-300000, -5000]
    # subtotal soma só a linha kind=result (CUSTO_DIRETO), não a informational (INVESTIMENTO)
    assert group["subtotal_cents"] == [-5000]
