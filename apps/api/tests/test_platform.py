"""Testes do Super Admin (Master). Delete real (purga) é coberto no e2e Docker (usa Postgres)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.modules.auth.models import Tenant, User

ADMIN_EMAIL = "master@e1p.com"
ADMIN_PASS = "senha-do-master-123"


@pytest.fixture()
def admin_headers(client: TestClient, db: Session) -> dict[str, str]:
    t = Tenant(slug="platform", legal_name="Plataforma", document="00000000000")
    db.add(t)
    db.flush()
    db.add(
        User(
            tenant_id=t.id,
            email=ADMIN_EMAIL,
            name="Master",
            password_hash=hash_password(ADMIN_PASS),
            role="owner",
            allowed_modules=[],
            is_platform_admin=True,
        )
    )
    db.commit()
    token = client.post(
        "/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _account_payload(**over):
    base = {
        "legal_name": "Cliente Pagante",
        "document": "12345678000190",
        "slug": "clientepagante",
        "email": "cliente@example.com",
        "name": "Cliente",
        "password": "senha-bem-grande",
    }
    return {**base, **over}


def test_non_admin_forbidden(client: TestClient):
    # usuário comum não acessa /admin
    token = client.post(
        "/auth/register",
        json=_account_payload(slug="comum", email="comum@example.com"),
    ).json()["access_token"]
    resp = client.get("/admin/accounts", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_unauthenticated_forbidden(client: TestClient):
    assert client.get("/admin/accounts").status_code == 401


def test_admin_creates_and_lists_account(client: TestClient, admin_headers):
    resp = client.post("/admin/accounts", json=_account_payload(), headers=admin_headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["owner"]["email"] == "cliente@example.com"

    listed = client.get("/admin/accounts", headers=admin_headers).json()
    emails = [a["owner"]["email"] for a in listed]
    assert "cliente@example.com" in emails
    # a conta do próprio admin NÃO aparece na lista
    assert "master@e1p.com" not in emails


def test_admin_deactivates_account(client: TestClient, admin_headers):
    created = client.post("/admin/accounts", json=_account_payload(), headers=admin_headers).json()
    uid = created["owner"]["id"]
    resp = client.patch(f"/admin/accounts/{uid}", json={"is_active": False}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False
    # usuário desativado não consegue logar
    login = client.post(
        "/auth/login", json={"email": "cliente@example.com", "password": "senha-bem-grande"}
    )
    assert login.status_code == 403


def test_cannot_edit_platform_admin(client: TestClient, admin_headers, db: Session):
    admin = db.query(User).filter(User.is_platform_admin.is_(True)).first()
    resp = client.patch(
        f"/admin/accounts/{admin.id}", json={"is_active": False}, headers=admin_headers
    )
    assert resp.status_code == 400
