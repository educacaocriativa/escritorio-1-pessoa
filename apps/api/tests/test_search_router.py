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


def test_depth_deep_conta_e_traz_trecho(client: TestClient, headers):
    client.post(
        "/crm/clients",
        json={"name": "Zulmira", "notes": "prefere ser chamada de Zu"},
        headers=headers,
    )

    raso = client.get("/search", params={"q": "chamada"}, headers=headers).json()
    fundo = client.get(
        "/search", params={"q": "chamada", "depth": "deep"}, headers=headers
    ).json()

    assert raso == {"groups": []}, "notas não são lidas na camada rasa"
    grupo = fundo["groups"][0]
    assert grupo["total"] == 1
    assert "chamada" in grupo["items"][0]["snippet"]


def test_depth_invalido_e_422(client: TestClient, headers):
    """O contrato é fechado: `depth` só aceita os dois valores que o serviço entende."""
    r = client.get("/search", params={"q": "ana", "depth": "profundissimo"}, headers=headers)

    assert r.status_code == 422
