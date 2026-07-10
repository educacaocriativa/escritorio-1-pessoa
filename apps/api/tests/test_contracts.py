"""Testes do Construtor de Contratos + assinatura pública (KYC)."""
import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Contratos SA",
    "document": "23232323000106",
    "slug": "contratosa",
    "email": "contr@example.com",
    "name": "Co",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _contract(**over):
    base = {
        "title": "Prestação de serviços",
        "clauses": [
            {"title": "Objeto", "text": "Serviço para [CLIENTE] por [VALOR]."},
            {"title": "Empresa", "text": "Contratada: [EMPRESA] em [DATA]."},
        ],
    }
    return {**base, **over}


def test_default_templates_seeded(client: TestClient, headers):
    resp = client.get("/contracts/templates", headers=headers)
    assert resp.status_code == 200
    names = [t["name"] for t in resp.json()]
    assert "Prestação de serviços" in names
    assert "Confidencialidade (NDA)" in names


def test_create_fills_variables(client: TestClient, headers):
    cl = client.post("/crm/clients", json={"name": "Maria"}, headers=headers).json()
    payload = _contract(client_id=cl["id"], variables={"VALOR": "R$ 1.000"})
    c = client.post("/contracts", json=payload, headers=headers).json()
    texts = " ".join(cl_["text"] for cl_ in c["clauses"])
    assert "R$ 1.000" in texts  # [VALOR]
    assert "Maria" in texts  # [CLIENTE] automático
    assert "Contratos SA" in texts  # [EMPRESA] automático
    assert "[" not in texts  # nada de placeholder solto conhecido
    assert c["public_slug"]
    assert c["status"] == "draft"


def test_public_view_and_sign(client: TestClient, headers):
    c = client.post("/contracts", json=_contract(), headers=headers).json()
    slug = c["public_slug"]
    # visão pública
    pub = client.get(f"/public/contracts/{slug}")
    assert pub.status_code == 200
    assert pub.json()["company_name"] == "Contratos SA"
    # assinar (KYC: nome + documento)
    sign = client.post(
        f"/public/contracts/{slug}/sign",
        json={"name": "João Cliente", "document": "529.982.247-25", "accept": True},
    )
    assert sign.status_code == 200, sign.text
    assert sign.json()["status"] == "signed"
    # contrato ficou assinado com os dados do assinante
    got = client.get(f"/contracts/{c['id']}", headers=headers).json()
    assert got["status"] == "signed"
    assert got["signer_name"] == "João Cliente"
    # KYC: documento validado (CPF real) e gravado NORMALIZADO (só-dígitos).
    assert got["signer_document"] == "52998224725"
    assert got["signed_at"]


def test_cannot_sign_twice(client: TestClient, headers):
    c = client.post("/contracts", json=_contract(), headers=headers).json()
    slug = c["public_slug"]
    body = {"name": "A B", "document": "52998224725", "accept": True}
    assert client.post(f"/public/contracts/{slug}/sign", json=body).status_code == 200
    assert client.post(f"/public/contracts/{slug}/sign", json=body).status_code == 409


def test_sign_requires_accept(client: TestClient, headers):
    c = client.post("/contracts", json=_contract(), headers=headers).json()
    resp = client.post(
        f"/public/contracts/{c['public_slug']}/sign",
        json={"name": "A B", "document": "52998224725", "accept": False},
    )
    assert resp.status_code == 400


def test_send_marks_sent(client: TestClient, headers):
    cl = client.post("/crm/clients", json={"name": "Cli"}, headers=headers).json()
    c = client.post("/contracts", json=_contract(client_id=cl["id"]), headers=headers).json()
    resp = client.post(f"/contracts/{c['id']}/send", headers=headers)
    assert resp.json()["status"] == "sent"


def test_cannot_edit_after_sent(client: TestClient, headers):
    c = client.post("/contracts", json=_contract(), headers=headers).json()
    client.post(f"/contracts/{c['id']}/send", headers=headers)
    resp = client.patch(f"/contracts/{c['id']}", json={"title": "Novo"}, headers=headers)
    assert resp.status_code == 409


def test_summary(client: TestClient, headers):
    c = client.post("/contracts", json=_contract(), headers=headers).json()
    client.post(f"/public/contracts/{c['public_slug']}/sign",
                json={"name": "X Y", "document": "52998224725", "accept": True})
    client.post("/contracts", json=_contract(), headers=headers)  # draft
    s = client.get("/contracts/summary", headers=headers).json()
    assert s["signed_count"] == 1
    assert s["draft_count"] == 1


def test_requires_auth(client: TestClient):
    assert client.get("/contracts/summary").status_code == 401