"""Testes de Produtos, Cupons e Alunos."""
import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Prod Co",
    "document": "15151515000166",
    "slug": "prodco",
    "email": "prod@example.com",
    "name": "Pr",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _product(**over):
    return {"name": "Curso X", "kind": "membership", "price_cents": 20000, **over}


def test_create_product(client: TestClient, headers):
    resp = client.post("/products", json=_product(), headers=headers)
    assert resp.status_code == 201, resp.text
    p = resp.json()
    assert p["active"] is True
    assert p["students"] == 0
    assert "/checkout/" in p["checkout_url"]


def test_invalid_kind_rejected(client: TestClient, headers):
    resp = client.post("/products", json=_product(kind="curso"), headers=headers)
    assert resp.status_code == 422


def test_sell_creates_enrollment_and_wallet_split(client: TestClient, headers):
    p = client.post("/products", json=_product(price_cents=20000), headers=headers).json()
    resp = client.post(
        f"/products/{p['id']}/sell",
        json={"name": "Aluno 1", "email": "aluno@example.com", "method": "pix"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    enr = resp.json()
    assert enr["amount_cents"] == 20000
    assert enr["product_name"] == "Curso X"
    # produto (40%) -> líquido 60% = 12000 disponível na carteira
    s = client.get("/wallet/summary", headers=headers).json()
    assert s["available_cents"] == 12000
    # aparece na lista de alunos
    alunos = client.get("/products/enrollments", headers=headers).json()
    assert alunos[0]["name"] == "Aluno 1"


def test_coupon_percent_applied_on_sale(client: TestClient, headers):
    p = client.post("/products", json=_product(price_cents=10000), headers=headers).json()
    client.post(
        "/products/coupons",
        json={"code": "promo10", "discount_type": "percent", "discount_value": 10},
        headers=headers,
    )
    enr = client.post(
        f"/products/{p['id']}/sell",
        json={"name": "Comprador", "coupon_code": "PROMO10"},
        headers=headers,
    ).json()
    assert enr["amount_cents"] == 9000  # 10% off de R$100


def test_coupon_fixed_applied(client: TestClient, headers):
    p = client.post("/products", json=_product(price_cents=10000), headers=headers).json()
    client.post(
        "/products/coupons",
        json={"code": "menos20", "discount_type": "fixed", "discount_value": 2000},
        headers=headers,
    )
    enr = client.post(
        f"/products/{p['id']}/sell",
        json={"name": "C", "coupon_code": "menos20"},
        headers=headers,
    ).json()
    assert enr["amount_cents"] == 8000


def test_duplicate_coupon_rejected(client: TestClient, headers):
    client.post(
        "/products/coupons",
        json={"code": "dup", "discount_type": "percent", "discount_value": 5},
        headers=headers,
    )
    resp = client.post(
        "/products/coupons",
        json={"code": "DUP", "discount_type": "percent", "discount_value": 5},
        headers=headers,
    )
    assert resp.status_code == 409


def test_percent_over_100_rejected(client: TestClient, headers):
    resp = client.post(
        "/products/coupons",
        json={"code": "x", "discount_type": "percent", "discount_value": 150},
        headers=headers,
    )
    assert resp.status_code == 422


def test_requires_auth(client: TestClient):
    assert client.get("/products").status_code == 401
