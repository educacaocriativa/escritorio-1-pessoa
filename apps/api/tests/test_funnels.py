"""Testes do Construtor de Funil de Vendas."""
import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Funil SA",
    "document": "31313131000122",
    "slug": "funilsa",
    "email": "funil@example.com",
    "name": "Fu",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_components_catalog(client: TestClient, headers):
    resp = client.get("/funnels/components", headers=headers)
    assert resp.status_code == 200
    cats = {c["category"] for c in resp.json()}
    assert {"gatilhos", "logica", "acoes", "comunicacao", "trafego"} <= cats
    # cada categoria tem itens e cor
    for c in resp.json():
        assert c["items"] and c["color"].startswith("#")


def test_create_and_get(client: TestClient, headers):
    nodes = [
        {"id": "n1", "type": "funnelNode", "position": {"x": 0, "y": 0},
         "data": {"label": "Página de Captura", "category": "gatilhos"}},
        {"id": "n2", "type": "funnelNode", "position": {"x": 200, "y": 100},
         "data": {"label": "Enviar E-mail", "category": "comunicacao"}},
    ]
    edges = [{"id": "e1", "source": "n1", "target": "n2"}]
    f = client.post("/funnels", json={"name": "Meu funil", "nodes": nodes, "edges": edges},
                    headers=headers).json()
    assert f["name"] == "Meu funil"
    assert len(f["nodes"]) == 2
    assert len(f["edges"]) == 1
    got = client.get(f"/funnels/{f['id']}", headers=headers).json()
    assert got["nodes"][1]["data"]["label"] == "Enviar E-mail"


def test_list_summary(client: TestClient, headers):
    client.post("/funnels", json={"name": "F1", "nodes": [{"id": "a"}]}, headers=headers)
    resp = client.get("/funnels", headers=headers).json()
    assert resp[0]["name"] == "F1"
    assert resp[0]["node_count"] == 1


def test_update_graph(client: TestClient, headers):
    f = client.post("/funnels", json={"name": "F"}, headers=headers).json()
    resp = client.patch(
        f"/funnels/{f['id']}",
        json={"nodes": [{"id": "x"}, {"id": "y"}],
              "edges": [{"id": "e", "source": "x", "target": "y"}]},
        headers=headers,
    )
    assert resp.status_code == 200
    assert len(resp.json()["nodes"]) == 2


def test_delete(client: TestClient, headers):
    f = client.post("/funnels", json={"name": "Apagar"}, headers=headers).json()
    assert client.delete(f"/funnels/{f['id']}", headers=headers).status_code == 204
    assert client.get(f"/funnels/{f['id']}", headers=headers).status_code == 404


def test_requires_name(client: TestClient, headers):
    assert client.post("/funnels", json={"nodes": []}, headers=headers).status_code == 422


def test_ai_compose_email(client: TestClient, headers):
    resp = client.post(
        "/funnels/ai-compose",
        json={"kind": "email", "prompt": "boas-vindas para novo aluno"},
        headers=headers,
    )
    assert resp.status_code == 200
    out = resp.json()
    assert out["subject"]  # e-mail tem assunto
    assert out["body"]


def test_ai_compose_whatsapp(client: TestClient, headers):
    resp = client.post(
        "/funnels/ai-compose",
        json={"kind": "whatsapp", "prompt": "lembrete de pagamento"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["body"]


def test_requires_auth(client: TestClient):
    assert client.get("/funnels").status_code == 401
