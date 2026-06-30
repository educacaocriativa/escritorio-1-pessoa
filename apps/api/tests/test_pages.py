"""Testes do construtor de páginas + página pública + captura de lead."""
import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Sites SA",
    "document": "41414141000133",
    "slug": "sitessa",
    "email": "sites@example.com",
    "name": "Si",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_create_uses_model_template_and_brand(client: TestClient, headers):
    client.patch("/settings/profile", json={"primary_color": "#123456"}, headers=headers)
    p = client.post("/pages", json={"title": "Landing", "model": "captura"}, headers=headers).json()
    assert p["model"] == "captura"
    assert any(b["type"] == "form" for b in p["blocks"])  # template de captura tem form
    assert p["primary_color"] == "#123456"  # herdou o brand kit
    assert p["public_slug"]
    assert p["status"] == "draft"


def test_public_only_after_publish(client: TestClient, headers):
    p = client.post("/pages", json={"title": "Vendas", "model": "vendas"}, headers=headers).json()
    slug = p["public_slug"]
    assert client.get(f"/public/pages/{slug}").status_code == 404  # rascunho não é público
    client.post(f"/pages/{p['id']}/publish", headers=headers)
    pub = client.get(f"/public/pages/{slug}")
    assert pub.status_code == 200
    assert pub.json()["title"] == "Vendas"


def test_form_submit_creates_lead(client: TestClient, headers):
    p = client.post("/pages", json={"title": "Captura", "model": "captura"}, headers=headers).json()
    client.post(f"/pages/{p['id']}/publish", headers=headers)
    resp = client.post(
        f"/public/pages/{p['public_slug']}/submit",
        json={"name": "Lead da Página", "email": "lead@example.com", "phone": "11999"},
    )
    assert resp.status_code == 200
    clients = client.get("/crm/clients", headers=headers).json()
    lead = [c for c in clients if c["name"] == "Lead da Página"]
    assert lead and lead[0]["source"] == "landing"


def test_update_blocks_and_publish_sync(client: TestClient, headers):
    p = client.post("/pages", json={"title": "X", "model": "conteudo"}, headers=headers).json()
    client.post(f"/pages/{p['id']}/publish", headers=headers)
    client.patch(
        f"/pages/{p['id']}",
        json={"blocks": [{"type": "heading", "text": "Novo título"}]},
        headers=headers,
    )
    pub = client.get(f"/public/pages/{p['public_slug']}").json()
    assert pub["blocks"][0]["text"] == "Novo título"  # snapshot público atualizado


def test_unpublish_hides(client: TestClient, headers):
    p = client.post("/pages", json={"title": "Y", "model": "conteudo"}, headers=headers).json()
    client.post(f"/pages/{p['id']}/publish", headers=headers)
    client.post(f"/pages/{p['id']}/unpublish", headers=headers)
    assert client.get(f"/public/pages/{p['public_slug']}").status_code == 404


def test_requires_auth(client: TestClient):
    assert client.get("/pages").status_code == 401
