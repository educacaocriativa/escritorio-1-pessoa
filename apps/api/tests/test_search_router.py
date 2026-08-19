"""A rota da busca global."""
import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Estúdio Ana",
    "document": "11222333000181",
    "slug": "estudioana",
    "email": "ana@example.com",
    "name": "Ana",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_agrupa_por_tipo(client: TestClient, headers):
    client.post("/crm/clients", json={"name": "Ana Souza"}, headers=headers)

    r = client.get("/search", params={"q": "ana"}, headers=headers)

    assert r.status_code == 200
    grupos = r.json()["groups"]
    assert grupos[0]["type"] == "client"
    assert grupos[0]["items"][0]["title"] == "Ana Souza"
    assert grupos[0]["items"][0]["route"].startswith("/crm/clients/")


def test_camada_rasa_nao_conta(client: TestClient, headers):
    """`has_more` em vez de `total`: sete `count()` por tecla, para um número que ninguém pediu."""
    client.post("/crm/clients", json={"name": "Ana Souza"}, headers=headers)

    grupo = client.get("/search", params={"q": "ana"}, headers=headers).json()["groups"][0]

    assert grupo["has_more"] is False
    assert grupo["total"] is None


def test_termo_curto_devolve_vazio(client: TestClient, headers):
    client.post("/crm/clients", json={"name": "Ana Souza"}, headers=headers)

    r = client.get("/search", params={"q": "a"}, headers=headers)

    assert r.status_code == 200
    assert r.json() == {"groups": []}


def test_porcento_nao_devolve_tudo(client: TestClient, headers):
    client.post("/crm/clients", json={"name": "Ana Souza"}, headers=headers)

    r = client.get("/search", params={"q": "%%"}, headers=headers)

    assert r.json() == {"groups": []}


def test_sem_token_e_401(client: TestClient):
    assert client.get("/search", params={"q": "ana"}).status_code == 401
