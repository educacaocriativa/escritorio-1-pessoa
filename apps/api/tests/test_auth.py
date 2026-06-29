"""Testes do módulo auth: registro, login, /me e isolamento básico."""
from fastapi.testclient import TestClient

VALID = {
    "legal_name": "João Silva Advocacia",
    "document": "12345678000190",
    "slug": "joaosilva",
    "email": "joao@example.com",
    "name": "João Silva",
    "password": "senha-super-secreta",
}


def _register(client: TestClient, **overrides):
    return client.post("/auth/register", json={**VALID, **overrides})


def test_register_creates_tenant_and_owner(client: TestClient):
    resp = _register(client)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["tenant"]["slug"] == "joaosilva"
    assert body["user"]["role"] == "owner"
    assert body["user"]["email"] == "joao@example.com"


def test_password_is_not_returned(client: TestClient):
    body = _register(client).json()
    assert "password" not in body["user"]
    assert "password_hash" not in body["user"]


def test_duplicate_slug_rejected(client: TestClient):
    _register(client)
    resp = _register(client, email="outro@example.com")
    assert resp.status_code == 409
    assert "subdomínio" in resp.json()["detail"].lower()


def test_duplicate_email_rejected(client: TestClient):
    _register(client)
    resp = _register(client, slug="outroslug")
    assert resp.status_code == 409
    assert "e-mail" in resp.json()["detail"].lower()


def test_invalid_slug_rejected(client: TestClient):
    resp = _register(client, slug="Joao Silva!")
    assert resp.status_code == 422


def test_reserved_slug_rejected(client: TestClient):
    resp = _register(client, slug="api")
    assert resp.status_code == 422


def test_login_success(client: TestClient):
    _register(client)
    resp = client.post("/auth/login", json={"email": VALID["email"], "password": VALID["password"]})
    assert resp.status_code == 200
    assert resp.json()["access_token"]


def test_login_wrong_password(client: TestClient):
    _register(client)
    resp = client.post("/auth/login", json={"email": VALID["email"], "password": "errada"})
    assert resp.status_code == 401


def test_login_unknown_email(client: TestClient):
    resp = client.post("/auth/login", json={"email": "ninguem@example.com", "password": "x"})
    assert resp.status_code == 401


def test_me_with_token(client: TestClient):
    token = _register(client).json()["access_token"]
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == VALID["email"]


def test_me_without_token(client: TestClient):
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_me_does_not_reissue_token(client: TestClient):
    token = _register(client).json()["access_token"]
    body = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    # /me retorna só identidade — não emite nova credencial num GET
    assert "access_token" not in body
    assert body["user"]["created_at"]
    assert body["tenant"]["created_at"]


def test_email_is_case_insensitive(client: TestClient):
    _register(client, email="Joao@Example.com")
    # login com caixa diferente funciona
    resp = client.post(
        "/auth/login",
        json={"email": "JOAO@example.COM", "password": VALID["password"]},
    )
    assert resp.status_code == 200


def test_duplicate_email_different_case_rejected(client: TestClient):
    _register(client, email="Joao@Example.com")
    resp = _register(client, slug="outro", email="joao@example.com")
    assert resp.status_code == 409
