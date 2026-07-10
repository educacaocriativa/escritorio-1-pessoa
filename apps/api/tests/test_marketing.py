"""Testes do gerador de carrossel (Marketing)."""
import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Mkt SA",
    "document": "28282828000107",
    "slug": "mktsa",
    "email": "mkt@example.com",
    "name": "Mk",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_templates_available(client: TestClient, headers):
    resp = client.get("/marketing/carousels/templates", headers=headers)
    assert resp.status_code == 200
    keys = [t["key"] for t in resp.json()]
    assert "moderno" in keys and "juridico" in keys


def test_generate_fallback_slides(client: TestClient, headers):
    # sem ANTHROPIC_API_KEY no teste -> usa o fallback estruturado
    resp = client.post(
        "/marketing/carousels/generate",
        json={"topic": "Como economizar impostos", "slides": 5},
        headers=headers,
    )
    assert resp.status_code == 200
    out = resp.json()
    slides = out["slides"]
    assert len(slides) == 5
    assert slides[0]["kind"] == "cover"  # capa
    assert slides[-1]["kind"] == "cta"  # CTA
    assert "Salve" in slides[-1]["body"] or slides[-1]["heading"]
    assert out["caption"]  # legenda gerada
    assert out["hashtags"].startswith("#")  # hashtags geradas


def test_generate_min_max(client: TestClient, headers):
    gen = "/marketing/carousels/generate"

    def status(n):
        return client.post(gen, json={"topic": "x y z", "slides": n}, headers=headers).status_code

    assert status(2) == 422
    assert status(11) == 422


def test_create_and_customize(client: TestClient, headers):
    payload = {
        "topic": "Direitos do consumidor",
        "slides": [{"heading": "Você sabia?", "body": "Seus direitos."}],
        "template": "juridico",
        "primary_color": "#1E3A5F",
        "font": "Georgia",
    }
    payload["handle"] = "@meuperfil"
    payload["caption"] = "Legenda teste"
    c = client.post("/marketing/carousels", json=payload, headers=headers).json()
    assert c["template"] == "juridico"
    assert c["primary_color"] == "#1E3A5F"
    assert c["font"] == "Georgia"
    assert c["handle"] == "@meuperfil"
    assert c["caption"] == "Legenda teste"
    assert len(c["slides"]) == 1


def test_update_slides_and_status(client: TestClient, headers):
    c = client.post("/marketing/carousels", json={"topic": "Tema teste"}, headers=headers).json()
    resp = client.patch(
        f"/marketing/carousels/{c['id']}",
        json={"status": "ready", "slides": [{"heading": "A", "body": "B"}],
              "accent_color": "#FFD93D"},
        headers=headers,
    )
    assert resp.status_code == 200
    out = resp.json()
    assert out["status"] == "ready"
    assert out["accent_color"] == "#FFD93D"
    assert out["slides"][0]["heading"] == "A"


def test_delete(client: TestClient, headers):
    c = client.post("/marketing/carousels", json={"topic": "Apagar"}, headers=headers).json()
    assert client.delete(f"/marketing/carousels/{c['id']}", headers=headers).status_code == 204
    assert client.get(f"/marketing/carousels/{c['id']}", headers=headers).status_code == 404


def test_requires_auth(client: TestClient):
    assert client.get("/marketing/carousels").status_code == 401
