"""Testes do plano de contas (Story 5.1) — funcionais em SQLite in-memory.

RLS (isolamento cross-tenant) é Postgres-only e NÃO é exercida aqui — está no arquivo dedicado
`test_chart_of_accounts_rls.py` (marker rls_e2e, testcontainers), mesmo padrão de
test_rls_isolation.py.
"""
import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Contas Co",
    "document": "12345678000195",
    "slug": "contasco",
    "email": "contas@example.com",
    "name": "Contas",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_create_account(client: TestClient, headers):
    resp = client.post(
        "/chart-of-accounts",
        json={"grupo_dre": "RECEITA", "categoria": "Consultoria"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["grupo_dre"] == "RECEITA"
    assert body["categoria"] == "Consultoria"
    assert body["archived_at"] is None


def test_create_invalid_group_is_422(client: TestClient, headers):
    resp = client.post(
        "/chart-of-accounts",
        json={"grupo_dre": "MARKETING", "categoria": "Ads"},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


def test_empty_categoria_is_422(client: TestClient, headers):
    resp = client.post(
        "/chart-of-accounts",
        json={"grupo_dre": "RECEITA", "categoria": "   "},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


def test_duplicate_categoria_in_group_is_409(client: TestClient, headers):
    payload = {"grupo_dre": "DESPESA_FIXA", "categoria": "Aluguel"}
    assert client.post("/chart-of-accounts", json=payload, headers=headers).status_code == 201
    dup = client.post("/chart-of-accounts", json=payload, headers=headers)
    assert dup.status_code == 409, dup.text


def test_same_categoria_different_group_is_allowed(client: TestClient, headers):
    a = client.post(
        "/chart-of-accounts",
        json={"grupo_dre": "RECEITA", "categoria": "Juros"},
        headers=headers,
    )
    b = client.post(
        "/chart-of-accounts",
        json={"grupo_dre": "FINANCEIRO", "categoria": "Juros"},
        headers=headers,
    )
    assert a.status_code == 201
    assert b.status_code == 201, b.text  # unicidade é POR grupo


def test_hierarchy_returns_all_six_groups_in_order(client: TestClient, headers):
    client.post(
        "/chart-of-accounts",
        json={"grupo_dre": "RECEITA", "categoria": "Consultoria"},
        headers=headers,
    )
    resp = client.get("/chart-of-accounts/hierarchy", headers=headers)
    assert resp.status_code == 200, resp.text
    groups = resp.json()
    assert [g["grupo_dre"] for g in groups] == [
        "RECEITA",
        "CUSTO_DIRETO",
        "DESPESA_FIXA",
        "TRIBUTOS",
        "FINANCEIRO",
        "INVESTIMENTO",
    ]
    receita = next(g for g in groups if g["grupo_dre"] == "RECEITA")
    assert [c["categoria"] for c in receita["categorias"]] == ["Consultoria"]


def test_update_renames_categoria(client: TestClient, headers):
    created = client.post(
        "/chart-of-accounts",
        json={"grupo_dre": "TRIBUTOS", "categoria": "ISS"},
        headers=headers,
    ).json()
    resp = client.patch(
        f"/chart-of-accounts/{created['id']}",
        json={"categoria": "Impostos sobre serviço"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["categoria"] == "Impostos sobre serviço"
    assert resp.json()["grupo_dre"] == "TRIBUTOS"  # grupo é fixo, não muda


def test_update_to_conflicting_name_is_409(client: TestClient, headers):
    client.post(
        "/chart-of-accounts",
        json={"grupo_dre": "RECEITA", "categoria": "Vendas"},
        headers=headers,
    )
    other = client.post(
        "/chart-of-accounts",
        json={"grupo_dre": "RECEITA", "categoria": "Serviços"},
        headers=headers,
    ).json()
    resp = client.patch(
        f"/chart-of-accounts/{other['id']}",
        json={"categoria": "Vendas"},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text


def test_archive_preserves_row_and_hides_from_default_list(client: TestClient, headers):
    created = client.post(
        "/chart-of-accounts",
        json={"grupo_dre": "INVESTIMENTO", "categoria": "Equipamentos"},
        headers=headers,
    ).json()

    arch = client.post(f"/chart-of-accounts/{created['id']}/archive", headers=headers)
    assert arch.status_code == 200, arch.text
    assert arch.json()["archived_at"] is not None  # a linha continua existindo (não deletada)

    default = client.get("/chart-of-accounts", headers=headers).json()
    assert all(a["id"] != created["id"] for a in default)  # some da listagem padrão

    with_archived = client.get(
        "/chart-of-accounts?include_archived=true", headers=headers
    ).json()
    assert any(a["id"] == created["id"] for a in with_archived)  # reaparece com o flag


def test_archived_categoria_still_blocks_duplicate(client: TestClient, headers):
    """Arquivar não apaga a linha — a UniqueConstraint continua ativa (histórico preservado)."""
    created = client.post(
        "/chart-of-accounts",
        json={"grupo_dre": "CUSTO_DIRETO", "categoria": "Insumos"},
        headers=headers,
    ).json()
    client.post(f"/chart-of-accounts/{created['id']}/archive", headers=headers)
    dup = client.post(
        "/chart-of-accounts",
        json={"grupo_dre": "CUSTO_DIRETO", "categoria": "Insumos"},
        headers=headers,
    )
    assert dup.status_code == 409, dup.text


def test_seed_is_idempotent(client: TestClient, headers):
    first = client.post("/chart-of-accounts/seed", headers=headers)
    assert first.status_code == 200, first.text
    count_after_first = len(first.json())
    assert count_after_first > 0
    # roda de novo: não duplica
    second = client.post("/chart-of-accounts/seed", headers=headers)
    assert second.status_code == 200, second.text
    assert len(second.json()) == count_after_first
    # o hook da Story 5.6 está semeado
    financeiro = [a for a in second.json() if a["grupo_dre"] == "FINANCEIRO"]
    assert any(a["categoria"] == "Rendimento de aplicação" for a in financeiro)


def test_get_missing_account_is_404(client: TestClient, headers):
    resp = client.patch(
        "/chart-of-accounts/nao-existe",
        json={"categoria": "X"},
        headers=headers,
    )
    assert resp.status_code == 404, resp.text
