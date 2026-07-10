"""Testes do Controle de Estoque — itens, movimentações, alertas e baixa na venda."""

import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Estoque SA",
    "document": "37373737000160",
    "slug": "estoquesa",
    "email": "est@example.com",
    "name": "Es",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_create_item_with_initial_movement(client: TestClient, headers):
    item = client.post(
        "/stock/items",
        json={"name": "Camiseta", "quantity": 10, "unit_cost_cents": 2500, "min_quantity": 3},
        headers=headers,
    ).json()
    assert item["quantity"] == 10
    assert item["value_cents"] == 25000  # 10 * 2500
    assert item["low"] is False
    movs = client.get(f"/stock/items/{item['id']}/movements", headers=headers).json()
    assert len(movs) == 1 and movs[0]["delta"] == 10  # estoque inicial


def test_adjust_in_and_out(client: TestClient, headers):
    item = client.post(
        "/stock/items", json={"name": "Caneca", "quantity": 5}, headers=headers
    ).json()
    client.post(
        f"/stock/items/{item['id']}/adjust",
        json={"delta": 8, "reason": "purchase"},
        headers=headers,
    )
    out = client.post(
        f"/stock/items/{item['id']}/adjust", json={"delta": -3, "reason": "loss"}, headers=headers
    )
    assert out.json()["quantity"] == 10  # 5 + 8 - 3
    movs = client.get(f"/stock/items/{item['id']}/movements", headers=headers).json()
    assert len(movs) == 3  # inicial + 2 ajustes


def test_cannot_go_negative_on_adjust(client: TestClient, headers):
    item = client.post("/stock/items", json={"name": "X", "quantity": 2}, headers=headers).json()
    resp = client.post(f"/stock/items/{item['id']}/adjust", json={"delta": -5}, headers=headers)
    assert resp.status_code == 409


def test_low_stock_alert_and_summary(client: TestClient, headers):
    client.post(
        "/stock/items",
        json={"name": "A", "quantity": 1, "min_quantity": 5, "unit_cost_cents": 100},
        headers=headers,
    )
    client.post(
        "/stock/items",
        json={"name": "B", "quantity": 50, "min_quantity": 5, "unit_cost_cents": 200},
        headers=headers,
    )
    low = client.get("/stock/low", headers=headers).json()
    assert len(low) == 1 and low[0]["name"] == "A"
    s = client.get("/stock/summary", headers=headers).json()
    assert s["item_count"] == 2
    assert s["low_stock_count"] == 1
    assert s["total_value_cents"] == 1 * 100 + 50 * 200


def test_sale_deducts_linked_stock(client: TestClient, headers):
    product = client.post(
        "/products",
        json={"name": "Boné", "kind": "physical", "price_cents": 5000},
        headers=headers,
    ).json()
    item = client.post(
        "/stock/items",
        json={"name": "Boné (estoque)", "quantity": 10, "product_id": product["id"]},
        headers=headers,
    ).json()
    client.post(
        f"/products/{product['id']}/sell",
        json={"name": "Comprador", "method": "pix"},
        headers=headers,
    )
    after = client.get(f"/stock/items/{item['id']}", headers=headers).json()
    assert after["quantity"] == 9  # baixa automática de 1
    movs = client.get(f"/stock/items/{item['id']}/movements", headers=headers).json()
    assert any(m["reason"] == "sale" and m["delta"] == -1 for m in movs)


def test_requires_auth(client: TestClient):
    assert client.get("/stock/summary").status_code == 401
