"""Testes de Configurações + Brand Kit."""
import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Brand SA",
    "document": "39393939000107",
    "slug": "brandsa",
    "email": "brand@example.com",
    "name": "Br",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_profile_created_with_defaults(client: TestClient, headers):
    resp = client.get("/settings/profile", headers=headers)
    assert resp.status_code == 200
    p = resp.json()
    assert p["display_name"] == "Brand SA"  # vem do legal_name
    assert p["document"] == "39393939000107"
    assert p["primary_color"] == "#5D44F8"
    assert p["font"] == "Inter"
    assert p["timezone"] == "America/Sao_Paulo"  # default de fuso (Story 4.5)


def test_update_timezone(client: TestClient, headers):
    resp = client.patch(
        "/settings/profile", json={"timezone": "America/Manaus"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["timezone"] == "America/Manaus"
    # persiste
    again = client.get("/settings/profile", headers=headers).json()
    assert again["timezone"] == "America/Manaus"


def test_update_brand_kit(client: TestClient, headers):
    resp = client.patch(
        "/settings/profile",
        json={
            "display_name": "Minha Marca",
            "primary_color": "#FF0000",
            "font": "Poppins",
            "logo_url": "https://x.com/logo.png",
            "phone": "+5511999998888",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    p = resp.json()
    assert p["display_name"] == "Minha Marca"
    assert p["primary_color"] == "#FF0000"
    assert p["font"] == "Poppins"
    # persiste
    again = client.get("/settings/profile", headers=headers).json()
    assert again["logo_url"] == "https://x.com/logo.png"
    assert again["phone"] == "+5511999998888"


def test_profile_is_singleton(client: TestClient, headers):
    client.get("/settings/profile", headers=headers)
    client.patch("/settings/profile", json={"display_name": "A"}, headers=headers)
    client.patch("/settings/profile", json={"display_name": "B"}, headers=headers)
    assert client.get("/settings/profile", headers=headers).json()["display_name"] == "B"


def test_update_invalid_timezone_rejected(client: TestClient, headers):
    resp = client.patch(
        "/settings/profile", json={"timezone": "Nao/Existe"}, headers=headers
    )
    assert resp.status_code == 422
    # não persistiu: segue o default
    again = client.get("/settings/profile", headers=headers).json()
    assert again["timezone"] == "America/Sao_Paulo"


def test_update_invalid_website_rejected(client: TestClient, headers):
    resp = client.patch(
        "/settings/profile", json={"website": "nao-e-uma-url"}, headers=headers
    )
    assert resp.status_code == 422
    again = client.get("/settings/profile", headers=headers).json()
    assert again["website"] == ""  # default vazio, não persistiu o lixo


def test_update_invalid_color_rejected(client: TestClient, headers):
    # cor por nome (não hex)
    resp = client.patch(
        "/settings/profile", json={"primary_color": "vermelho"}, headers=headers
    )
    assert resp.status_code == 422
    # hex com dígitos inválidos
    resp2 = client.patch(
        "/settings/profile", json={"primary_color": "#ZZZZZZ"}, headers=headers
    )
    assert resp2.status_code == 422
    # não persistiu: segue o default
    again = client.get("/settings/profile", headers=headers).json()
    assert again["primary_color"] == "#5D44F8"


def test_requires_auth(client: TestClient):
    assert client.get("/settings/profile").status_code == 401
