"""Testes do centro de custo — 2ª dimensão de análise (Story 5.5).

Cobre (Tasks 1-6 / AC1-3 / IV1-3):
- CRUD do centro de custo (criar/listar/editar/arquivar; unicidade de nome → 409; kind livre);
- vincular lançamento (conta a pagar/receber) a um centro de custo, e criar SEM centro continua
  funcionando (IV1 — dimensão sempre opcional);
- filtro por centro de custo na DRE (5.3) e na DRE por contrato (5.4) retorna só o subconjunto;
- REGRESSÃO byte-a-byte: `dre_report()`/`contract_dre()` SEM `cost_center_id` produzem o MESMO
  resultado da 5.3/5.4 mesmo com lançamentos tagueados — a visão padrão não muda (IV3);
- endpoint `by-cost-center`: agrega o resultado por centro (incl. bucket "Não atribuído" — AC3);
- 404 fail-closed ao vincular/filtrar por um centro inexistente (base do isolamento cross-tenant).

RLS/isolamento cross-tenant é validado à parte no Postgres real (test_cost_centers_rls.py,
`rls_e2e`) — aqui a suíte roda em SQLite (ver conftest).
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.contracts import service as contracts_service
from app.modules.financial_intelligence import dre as dre_service
from app.modules.financial_intelligence import profitability as profitability_service
from app.modules.payables.models import Payable
from app.modules.receivables.models import Charge

REGISTER = {
    "legal_name": "Consultoria Custo",
    "document": "11444777000161",
    "slug": "custo",
    "email": "custo@example.com",
    "name": "Cida",
    "password": "uma-senha-bem-grande",
}

START = "2026-07-01"
END = "2026-07-31"
D_START = date(2026, 7, 1)
D_END = date(2026, 7, 31)


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


def _cost_center(client: TestClient, headers, *, name: str, kind: str = "socio") -> dict:
    r = client.post("/cost-centers", json={"name": name, "kind": kind}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _charge(
    client, headers, *, amount, competence, account_id=None, cost_center_id=None, contract_id=None
):
    body = {
        "kind": "service",
        "method": "pix",
        "amount_cents": amount,
        "due_date": competence,
        "competence_date": competence,
    }
    if account_id:
        body["chart_account_id"] = account_id
    if cost_center_id:
        body["cost_center_id"] = cost_center_id
    if contract_id:
        body["contract_id"] = contract_id
    r = client.post("/receivables/charges", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _payable(
    client, headers, *, amount, competence, account_id=None, cost_center_id=None, contract_id=None
):
    body = {
        "description": "conta",
        "amount_cents": amount,
        "due_date": competence,
        "competence_date": competence,
    }
    if account_id:
        body["chart_account_id"] = account_id
    if cost_center_id:
        body["cost_center_id"] = cost_center_id
    if contract_id:
        body["contract_id"] = contract_id
    r = client.post("/payables/bills", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ── CRUD do centro de custo (AC1) ───────────────────────────────────────────
def test_requires_auth(client: TestClient):
    assert client.get("/cost-centers").status_code == 401


def test_crud_cost_center(client: TestClient, headers):
    cc = _cost_center(client, headers, name="Sócio A", kind="socio")
    assert cc["name"] == "Sócio A"
    assert cc["kind"] == "socio"
    assert cc["archived_at"] is None

    # listar
    lst = client.get("/cost-centers", headers=headers).json()
    assert [c["name"] for c in lst] == ["Sócio A"]

    # editar (nome + kind livre)
    r = client.patch(
        f"/cost-centers/{cc['id']}", json={"name": "Sócio Alpha", "kind": "unidade"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Sócio Alpha"
    assert r.json()["kind"] == "unidade"

    # arquivar (lógico) → some da listagem padrão, aparece com include_archived
    ar = client.post(f"/cost-centers/{cc['id']}/archive", headers=headers)
    assert ar.status_code == 200
    assert ar.json()["archived_at"] is not None
    assert client.get("/cost-centers", headers=headers).json() == []
    with_arch = client.get(
        "/cost-centers", params={"include_archived": True}, headers=headers
    ).json()
    assert len(with_arch) == 1


def test_duplicate_name_is_409(client: TestClient, headers):
    _cost_center(client, headers, name="Área X")
    r = client.post("/cost-centers", json={"name": "Área X"}, headers=headers)
    assert r.status_code == 409


def test_kind_is_free_text_defaults_outro(client: TestClient, headers):
    # kind é texto livre (não enum fechado como grupo_dre): aceita valor arbitrário; vazio → outro
    r = client.post(
        "/cost-centers", json={"name": "Livre", "kind": "  "}, headers=headers
    )
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "outro"
    r2 = client.post(
        "/cost-centers", json={"name": "Custom", "kind": "regional"}, headers=headers
    )
    assert r2.status_code == 201
    assert r2.json()["kind"] == "regional"


def test_empty_name_rejected(client: TestClient, headers):
    assert client.post("/cost-centers", json={"name": "   "}, headers=headers).status_code == 422


# ── Vínculo opcional (AC1 / IV1) ────────────────────────────────────────────
def test_link_charge_and_payable_to_cost_center(client: TestClient, headers):
    cc = _cost_center(client, headers, name="Sócio A")
    ch = _charge(client, headers, amount=10000, competence="2026-07-10", cost_center_id=cc["id"])
    assert ch["cost_center_id"] == cc["id"]
    pb = _payable(client, headers, amount=5000, competence="2026-07-11", cost_center_id=cc["id"])
    assert pb["cost_center_id"] == cc["id"]


def test_create_without_cost_center_still_works(client: TestClient, headers):
    """IV1: a 2ª dimensão é sempre opcional — criar sem informá-la não quebra nenhum fluxo."""
    ch = _charge(client, headers, amount=10000, competence="2026-07-10")
    assert ch["cost_center_id"] is None
    pb = _payable(client, headers, amount=5000, competence="2026-07-11")
    assert pb["cost_center_id"] is None


def test_relink_and_unlink_cost_center(client: TestClient, headers):
    cc = _cost_center(client, headers, name="Sócio A")
    ch = _charge(client, headers, amount=10000, competence="2026-07-10")
    assert ch["cost_center_id"] is None
    # vincula
    r = client.patch(
        f"/receivables/charges/{ch['id']}", json={"cost_center_id": cc["id"]}, headers=headers
    )
    assert r.status_code == 200 and r.json()["cost_center_id"] == cc["id"]
    # desvincula ("" → "Não atribuído")
    r2 = client.patch(
        f"/receivables/charges/{ch['id']}", json={"cost_center_id": ""}, headers=headers
    )
    assert r2.status_code == 200 and r2.json()["cost_center_id"] is None


def test_link_to_missing_cost_center_is_404(client: TestClient, headers):
    r = client.post(
        "/receivables/charges",
        json={
            "kind": "service", "method": "pix", "amount_cents": 1000,
            "due_date": "2026-07-10", "cost_center_id": "nao-existe",
        },
        headers=headers,
    )
    assert r.status_code == 404
    r2 = client.post(
        "/payables/bills",
        json={"amount_cents": 1000, "due_date": "2026-07-10", "cost_center_id": "nao-existe"},
        headers=headers,
    )
    assert r2.status_code == 404


# ── DRE por categoria (5.3) filtrada por centro de custo (AC2) ──────────────
def test_dre_filtered_by_cost_center(client: TestClient, headers):
    receita = _account(client, headers, "RECEITA", "Consultoria")
    a = _cost_center(client, headers, name="Sócio A")
    b = _cost_center(client, headers, name="Sócio B")
    _charge(client, headers, amount=100000, competence="2026-07-10",
            account_id=receita, cost_center_id=a["id"])
    _charge(client, headers, amount=40000, competence="2026-07-11",
            account_id=receita, cost_center_id=b["id"])
    _charge(client, headers, amount=7000, competence="2026-07-12", account_id=receita)  # sem centro

    def _dre(params):
        r = client.get("/financial-intelligence/dre", params=params, headers=headers)
        assert r.status_code == 200, r.text
        return r.json()

    # sem filtro (nulo) → TUDO (100000 + 40000 + 7000)
    full = _dre({"start": START, "end": END})
    receita_total = next(g for g in full["groups"] if g["grupo_dre"] == "RECEITA")["total_cents"]
    assert receita_total == 147000
    # filtrado pelo Sócio A → só 100000
    only_a = _dre({"start": START, "end": END, "cost_center_id": a["id"]})
    assert next(
        g for g in only_a["groups"] if g["grupo_dre"] == "RECEITA"
    )["total_cents"] == 100000


def test_dre_filter_missing_cost_center_is_404(client: TestClient, headers):
    r = client.get(
        "/financial-intelligence/dre",
        params={"start": START, "end": END, "cost_center_id": "nao-existe"},
        headers=headers,
    )
    assert r.status_code == 404


def test_dre_empty_cost_center_param_means_all(client: TestClient, headers):
    """`?cost_center_id=` (vazio) == 'Todos': mostra tudo (não filtra a zero) — IV3."""
    receita = _account(client, headers, "RECEITA", "Consultoria")
    a = _cost_center(client, headers, name="Sócio A")
    _charge(client, headers, amount=100000, competence="2026-07-10",
            account_id=receita, cost_center_id=a["id"])
    _charge(client, headers, amount=7000, competence="2026-07-11", account_id=receita)
    r = client.get(
        "/financial-intelligence/dre",
        params={"start": START, "end": END, "cost_center_id": ""},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert next(
        g for g in r.json()["groups"] if g["grupo_dre"] == "RECEITA"
    )["total_cents"] == 107000


# ── REGRESSÃO byte-a-byte (IV3): DRE sem filtro == Story 5.3 ────────────────
def _seed_5_3_scenario_with_cost_centers(client: TestClient, headers) -> None:
    """Dataset IDÊNTICO ao _seed_scenario da Story 5.3, mas com ALGUNS lançamentos tagueados a um
    centro de custo. A DRE SEM filtro deve ser byte-a-byte igual à 5.3 — o tag não muda a visão
    padrão (IV3)."""
    cc = _cost_center(client, headers, name="Sócio A")
    consult = _account(client, headers, "RECEITA", "Consultoria")
    mentoria = _account(client, headers, "RECEITA", "Mentoria")
    custo = _account(client, headers, "CUSTO_DIRETO", "Insumos")
    desp = _account(client, headers, "DESPESA_FIXA", "Aluguel")
    trib = _account(client, headers, "TRIBUTOS", "ISS")
    rend = _account(client, headers, "FINANCEIRO", "Rendimento")
    tarifa = _account(client, headers, "FINANCEIRO", "Tarifas")
    inv = _account(client, headers, "INVESTIMENTO", "Equipamentos")
    # Receitas (algumas com centro de custo, para provar a invariância do filtro nulo)
    _charge(client, headers, amount=100000, competence="2026-07-10",
            account_id=consult, cost_center_id=cc["id"])
    _charge(client, headers, amount=50000, competence="2026-07-20", account_id=consult)
    _charge(client, headers, amount=30000, competence="2026-07-15",
            account_id=mentoria, cost_center_id=cc["id"])
    _charge(client, headers, amount=2000, competence="2026-07-05", account_id=rend)
    _charge(client, headers, amount=999999, competence="2026-08-05", account_id=consult)  # fora
    _charge(client, headers, amount=7000, competence="2026-07-12", account_id=None)  # s/ categoria
    _payable(client, headers, amount=20000, competence="2026-07-08",
             account_id=custo, cost_center_id=cc["id"])
    _payable(client, headers, amount=40000, competence="2026-07-01", account_id=desp)
    _payable(client, headers, amount=10000, competence="2026-07-25", account_id=trib)
    _payable(client, headers, amount=500, competence="2026-07-03", account_id=tarifa)
    _payable(client, headers, amount=300000, competence="2026-07-02", account_id=inv)
    _payable(client, headers, amount=3000, competence="2026-07-18", account_id=None)  # s/ categoria


_EXPECTED_GROUPS = [
    {"grupo_dre": "RECEITA", "total_cents": 180000, "categorias": [
        {"categoria": "Consultoria", "amount_cents": 150000, "count": 2},
        {"categoria": "Mentoria", "amount_cents": 30000, "count": 1},
    ]},
    {"grupo_dre": "CUSTO_DIRETO", "total_cents": -20000, "categorias": [
        {"categoria": "Insumos", "amount_cents": -20000, "count": 1},
    ]},
    {"grupo_dre": "DESPESA_FIXA", "total_cents": -40000, "categorias": [
        {"categoria": "Aluguel", "amount_cents": -40000, "count": 1},
    ]},
    {"grupo_dre": "TRIBUTOS", "total_cents": -10000, "categorias": [
        {"categoria": "ISS", "amount_cents": -10000, "count": 1},
    ]},
    {"grupo_dre": "FINANCEIRO", "total_cents": 1500, "categorias": [
        {"categoria": "Rendimento", "amount_cents": 2000, "count": 1},
        {"categoria": "Tarifas", "amount_cents": -500, "count": 1},
    ]},
    {"grupo_dre": "INVESTIMENTO", "total_cents": -300000, "categorias": [
        {"categoria": "Equipamentos", "amount_cents": -300000, "count": 1},
    ]},
]


def test_dre_without_cost_center_is_byte_identical_to_5_3(client: TestClient, headers, db: Session):
    """IV3: chamar dre_report() SEM cost_center_id com o dataset da 5.3 (mesmo com lançamentos
    tagueados a um centro de custo) devolve resultado byte-a-byte idêntico ao da Story 5.3."""
    _seed_5_3_scenario_with_cost_centers(client, headers)
    report = dre_service.dre_report(db, start=D_START, end=D_END)  # cost_center_id=None (default)
    d = asdict(report)
    assert d["groups"] == _EXPECTED_GROUPS
    assert d["sem_categoria"] == {
        "grupo_dre": "SEM_CATEGORIA", "total_cents": 4000,
        "categorias": [{"categoria": "Sem categoria", "amount_cents": 4000, "count": 2}],
    }
    assert d["resultado_cents"] == 111500
    assert d["start"] == D_START and d["end"] == D_END


# ── DRE por contrato (5.4) filtrada + regressão (IV3) ───────────────────────
def _contract(client, headers, *, title="Projeto A", fixed_costs=None) -> dict:
    body = {"title": title, "clauses": [{"title": "Objeto", "text": "Serviços."}]}
    r = client.post("/contracts", json=body, headers=headers)
    assert r.status_code == 201, r.text
    c = r.json()
    if fixed_costs is not None:
        r2 = client.patch(
            f"/contracts/{c['id']}", json={"fixed_costs_allocated_cents": fixed_costs},
            headers=headers,
        )
        assert r2.status_code == 200, r2.text
    return c


def test_contract_dre_without_cost_center_is_unchanged(client: TestClient, headers, db: Session):
    """IV3: contract_dre() SEM cost_center_id == Story 5.4, mesmo com um lançamento tagueado."""
    cc = _cost_center(client, headers, name="Sócio A")
    receita = _account(client, headers, "RECEITA", "Consultoria")
    custo = _account(client, headers, "CUSTO_DIRETO", "Insumos")
    c = _contract(client, headers, fixed_costs=30000)
    _charge(client, headers, amount=100000, competence="2026-07-10",
            account_id=receita, cost_center_id=cc["id"], contract_id=c["id"])
    _payable(client, headers, amount=40000, competence="2026-07-12",
             account_id=custo, contract_id=c["id"])

    contract = contracts_service.get_contract(db, c["id"])
    report = profitability_service.contract_dre(db, contract=contract, start=D_START, end=D_END)
    assert report.receita_cents == 100000
    assert report.custo_direto_cents == -40000
    assert report.margem_contribuicao_cents == 60000
    assert report.resultado_cents == 30000  # 60000 − 30000 custo fixo


def test_contract_dre_filtered_by_cost_center(client: TestClient, headers):
    receita = _account(client, headers, "RECEITA", "Consultoria")
    a = _cost_center(client, headers, name="Sócio A")
    c = _contract(client, headers)
    # duas receitas do MESMO contrato: uma no Sócio A, outra sem centro de custo
    _charge(client, headers, amount=100000, competence="2026-07-10",
            account_id=receita, contract_id=c["id"], cost_center_id=a["id"])
    _charge(client, headers, amount=40000, competence="2026-07-11",
            account_id=receita, contract_id=c["id"])

    def _cdre(params):
        r = client.get(
            f"/financial-intelligence/contracts/{c['id']}/dre", params=params, headers=headers
        )
        assert r.status_code == 200, r.text
        return r.json()

    # sem filtro → 140000; filtrado pelo Sócio A → só 100000
    assert _cdre({"start": START, "end": END})["receita_cents"] == 140000
    assert _cdre(
        {"start": START, "end": END, "cost_center_id": a["id"]}
    )["receita_cents"] == 100000


def test_contract_dre_filter_missing_cost_center_is_404(client: TestClient, headers):
    c = _contract(client, headers)
    r = client.get(
        f"/financial-intelligence/contracts/{c['id']}/dre",
        params={"start": START, "end": END, "cost_center_id": "nao-existe"},
        headers=headers,
    )
    assert r.status_code == 404


# ── Endpoint by-cost-center (AC2/AC3) ───────────────────────────────────────
def test_by_cost_center_groups_including_nao_atribuido(client: TestClient, headers):
    receita = _account(client, headers, "RECEITA", "Consultoria")
    custo = _account(client, headers, "CUSTO_DIRETO", "Insumos")
    a = _cost_center(client, headers, name="Sócio A")
    b = _cost_center(client, headers, name="Sócio B")
    # A: receita 100000, custo 40000 → resultado 60000
    _charge(client, headers, amount=100000, competence="2026-07-10",
            account_id=receita, cost_center_id=a["id"])
    _payable(client, headers, amount=40000, competence="2026-07-12",
             account_id=custo, cost_center_id=a["id"])
    # B: receita 50000 → resultado 50000
    _charge(client, headers, amount=50000, competence="2026-07-10",
            account_id=receita, cost_center_id=b["id"])
    # sem centro (Não atribuído): receita 7000
    _charge(client, headers, amount=7000, competence="2026-07-11", account_id=receita)

    r = client.get(
        "/financial-intelligence/by-cost-center",
        params={"start": START, "end": END}, headers=headers,
    )
    assert r.status_code == 200, r.text
    buckets = {b["name"]: b for b in r.json()["buckets"]}
    assert buckets["Sócio A"]["receita_cents"] == 100000
    assert buckets["Sócio A"]["resultado_cents"] == 60000
    assert buckets["Sócio B"]["resultado_cents"] == 50000
    # bucket sintético "Não atribuído" (cost_center_id None) — AC3
    assert buckets["Não atribuído"]["cost_center_id"] is None
    assert buckets["Não atribuído"]["receita_cents"] == 7000
    # "Não atribuído" sempre por último
    assert r.json()["buckets"][-1]["name"] == "Não atribuído"


def test_by_cost_center_shows_zero_centers_for_comparison(client: TestClient, headers):
    """Centro sem movimento no período ainda aparece (comparar sócios lado a lado)."""
    _cost_center(client, headers, name="Sócio Ocioso")
    r = client.get(
        "/financial-intelligence/by-cost-center",
        params={"start": START, "end": END}, headers=headers,
    )
    names = [b["name"] for b in r.json()["buckets"]]
    assert "Sócio Ocioso" in names
    ocioso = next(b for b in r.json()["buckets"] if b["name"] == "Sócio Ocioso")
    assert ocioso["resultado_cents"] == 0 and ocioso["lancamentos"] == 0


def test_report_is_read_only(client: TestClient, headers, db: Session):
    """O cruzamento por centro de custo é SOMENTE LEITURA (IV1) — não altera lançamentos."""
    receita = _account(client, headers, "RECEITA", "Consultoria")
    a = _cost_center(client, headers, name="Sócio A")
    _charge(client, headers, amount=100000, competence="2026-07-10",
            account_id=receita, cost_center_id=a["id"])

    def snapshot():
        db.expire_all()
        charges = {c.id: (c.status, c.amount_cents, c.cost_center_id)
                   for c in db.scalars(select(Charge)).all()}
        payables = {p.id: (p.status, p.amount_cents, p.cost_center_id)
                    for p in db.scalars(select(Payable)).all()}
        return {"charges": charges, "payables": payables}

    before = snapshot()
    client.get("/financial-intelligence/by-cost-center",
               params={"start": START, "end": END}, headers=headers)
    client.get("/financial-intelligence/dre",
               params={"start": START, "end": END, "cost_center_id": a["id"]}, headers=headers)
    assert snapshot() == before
