"""Testes da Carteira & Split."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.modules.auth.models import Tenant, User
from app.modules.wallet.service import compute_split

REGISTER = {
    "legal_name": "Loja Bia",
    "document": "44555666000181",
    "slug": "lojabia",
    "email": "bia@example.com",
    "name": "Bia",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── split (unitário) ───────────────────────────────────


def test_split_40():
    assert compute_split(10000, 40) == (4000, 6000)  # 40% / 60%


def test_split_30():
    assert compute_split(10000, 30) == (3000, 7000)  # 30% / 70%


def test_split_rounds_half_up():
    # 40% de 999 = 399,6 -> 400 (meio-para-cima); líquido 599
    assert compute_split(999, 40) == (400, 599)


# ── transações ─────────────────────────────────────────


def test_create_pix_is_available(client: TestClient, headers):
    resp = client.post(
        "/wallet/transactions",
        json={"kind": "service", "method": "pix", "gross_cents": 10000, "description": "Consulta"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    tx = resp.json()
    assert tx["platform_fee_cents"] == 3000
    assert tx["net_cents"] == 7000
    assert tx["status"] == "available"


def test_create_card_is_pending(client: TestClient, headers):
    tx = client.post(
        "/wallet/transactions",
        json={"kind": "product", "method": "card", "gross_cents": 5000},
        headers=headers,
    ).json()
    assert tx["status"] == "pending"


def test_invalid_kind_rejected(client: TestClient, headers):
    resp = client.post(
        "/wallet/transactions",
        json={"kind": "doacao", "method": "pix", "gross_cents": 100},
        headers=headers,
    )
    assert resp.status_code == 422


def test_zero_amount_rejected(client: TestClient, headers):
    resp = client.post(
        "/wallet/transactions",
        json={"kind": "service", "method": "pix", "gross_cents": 0},
        headers=headers,
    )
    assert resp.status_code == 422


def test_wallet_summary(client: TestClient, headers):
    client.post(
        "/wallet/transactions",
        json={"kind": "service", "method": "pix", "gross_cents": 10000},
        headers=headers,
    )  # net 7000 available
    client.post(
        "/wallet/transactions",
        json={"kind": "product", "method": "card", "gross_cents": 10000},
        headers=headers,
    )  # net 6000 pending
    s = client.get("/wallet/summary", headers=headers).json()
    assert s["available_cents"] == 7000
    assert s["pending_cents"] == 6000
    assert s["gross_total_cents"] == 20000
    assert s["fees_total_cents"] == 3000 + 4000


def test_settle_moves_pending_to_available(client: TestClient, headers):
    tx = client.post(
        "/wallet/transactions",
        json={"kind": "product", "method": "card", "gross_cents": 10000},
        headers=headers,
    ).json()
    r = client.post(f"/wallet/transactions/{tx['id']}/settle", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "available"


def test_settle_non_pending_rejected(client: TestClient, headers):
    tx = client.post(
        "/wallet/transactions",
        json={"kind": "service", "method": "pix", "gross_cents": 10000},
        headers=headers,
    ).json()  # already available
    r = client.post(f"/wallet/transactions/{tx['id']}/settle", headers=headers)
    assert r.status_code == 409


def test_payout_withdraws_available(client: TestClient, headers):
    client.post(
        "/wallet/transactions",
        json={"kind": "service", "method": "pix", "gross_cents": 10000},
        headers=headers,
    )  # net 7000 available
    r = client.post("/wallet/payout", headers=headers)
    assert r.json()["amount_cents"] == 7000
    assert r.json()["transactions"] == 1
    # depois do saque, disponível zera
    assert client.get("/wallet/summary", headers=headers).json()["available_cents"] == 0


def test_requires_auth(client: TestClient):
    assert client.get("/wallet/summary").status_code == 401


# ── Story 5.10: classificação (plano de contas + centro de custo) ──────────────────────────────


def test_transaction_accepts_valid_chart_account(client: TestClient, headers):
    acc = client.post(
        "/chart-of-accounts",
        json={"grupo_dre": "RECEITA", "categoria": "Vendas avulsas"},
        headers=headers,
    ).json()
    tx = client.post(
        "/wallet/transactions",
        json={
            "kind": "service", "method": "pix", "gross_cents": 10000,
            "chart_account_id": acc["id"],
        },
        headers=headers,
    ).json()
    assert tx["chart_account_id"] == acc["id"]
    assert tx["competence_date"] is not None  # preenchida com a data de hoje por padrão


def test_transaction_rejects_unknown_chart_account(client: TestClient, headers):
    resp = client.post(
        "/wallet/transactions",
        json={
            "kind": "service", "method": "pix", "gross_cents": 100,
            "chart_account_id": "nao-existe",
        },
        headers=headers,
    )
    assert resp.status_code == 404, resp.text


def test_transaction_accepts_valid_cost_center(client: TestClient, headers):
    cc = client.post("/cost-centers", json={"name": "Loja física"}, headers=headers).json()
    tx = client.post(
        "/wallet/transactions",
        json={"kind": "service", "method": "pix", "gross_cents": 10000, "cost_center_id": cc["id"]},
        headers=headers,
    ).json()
    assert tx["cost_center_id"] == cc["id"]


def test_transaction_rejects_unknown_cost_center(client: TestClient, headers):
    resp = client.post(
        "/wallet/transactions",
        json={
            "kind": "service", "method": "pix", "gross_cents": 100,
            "cost_center_id": "nao-existe",
        },
        headers=headers,
    )
    assert resp.status_code == 404, resp.text


# ── Master: ganhos da plataforma ───────────────────────


def _make_admin(client: TestClient, db: Session) -> dict[str, str]:
    t = Tenant(slug="platform", legal_name="Plat", document="00000000000")
    db.add(t)
    db.flush()
    db.add(
        User(
            tenant_id=t.id,
            email="master@e1p.com",
            name="Master",
            password_hash=hash_password("senha-master-123"),
            role="owner",
            allowed_modules=[],
            is_platform_admin=True,
        )
    )
    db.commit()
    at = client.post(
        "/auth/login", json={"email": "master@e1p.com", "password": "senha-master-123"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {at}"}


def test_split_rates_master_defines_and_applies(client: TestClient, headers, db: Session):
    # usuário comum não acessa
    assert client.get("/wallet/split-rates", headers=headers).status_code == 403

    admin = _make_admin(client, db)
    # padrão 40/30/20
    assert client.get("/wallet/split-rates", headers=admin).json() == {
        "product_pct": 40,
        "service_pct": 30,
        "recurring_pct": 20,
    }
    # Master redefine
    client.put(
        "/wallet/split-rates",
        json={"product_pct": 50, "service_pct": 25, "recurring_pct": 10},
        headers=admin,
    )
    # nova venda de produto usa a nova taxa (50%)
    tx = client.post(
        "/wallet/transactions",
        json={"kind": "product", "method": "pix", "gross_cents": 10000},
        headers=headers,
    ).json()
    assert tx["platform_fee_cents"] == 5000
    assert tx["net_cents"] == 5000


def test_split_rate_above_limit_rejected(client: TestClient, db: Session):
    admin = _make_admin(client, db)
    resp = client.put(
        "/wallet/split-rates",
        json={"product_pct": 99, "service_pct": 30, "recurring_pct": 20},
        headers=admin,
    )
    assert resp.status_code == 422  # schema limita a 95%


def test_platform_earnings_master_only(client: TestClient, headers, db: Session):
    # tenant gera vendas
    client.post(
        "/wallet/transactions",
        json={"kind": "product", "method": "pix", "gross_cents": 10000},
        headers=headers,
    )  # fee 4000
    # usuário comum não acessa
    assert client.get("/wallet/platform-earnings", headers=headers).status_code == 403

    # cria um admin e consulta
    t = Tenant(slug="platform", legal_name="Plat", document="00000000000")
    db.add(t)
    db.flush()
    db.add(
        User(
            tenant_id=t.id,
            email="master@e1p.com",
            name="Master",
            password_hash=hash_password("senha-master-123"),
            role="owner",
            allowed_modules=[],
            is_platform_admin=True,
        )
    )
    db.commit()
    at = client.post(
        "/auth/login", json={"email": "master@e1p.com", "password": "senha-master-123"}
    ).json()["access_token"]
    earnings = client.get(
        "/wallet/platform-earnings", headers={"Authorization": f"Bearer {at}"}
    ).json()
    assert earnings["gmv_cents"] == 10000
    assert earnings["fees_cents"] == 4000
    assert earnings["by_kind"]["product"] == 4000
