"""Testes da bandeja de comprovantes (Contas a Pagar)."""
import io

import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Recibo Co",
    "document": "12345678000195",
    "slug": "reciboco",
    "email": "recibo@example.com",
    "name": "Recibo",
    "password": "senha-bem-comprida",
}

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _upload(client: TestClient, headers, *, name="comprovante.png", ctype="image/png", data=PNG):
    return client.post(
        "/payables/receipts",
        files={"file": (name, data, ctype)},
        headers=headers,
    )


def test_upload_cria_item_na_bandeja(client: TestClient, headers):
    resp = _upload(client, headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["filename"] == "comprovante.png"
    assert body["content_type"] == "image/png"
    assert body["size"] == len(PNG)

    bandeja = client.get("/payables/receipts", headers=headers).json()
    assert [i["id"] for i in bandeja] == [body["id"]]


def test_upload_recusa_tipo_nao_permitido(client: TestClient, headers):
    resp = _upload(client, headers, name="audio.ogg", ctype="audio/ogg", data=b"OggS____")
    assert resp.status_code == 415


def test_upload_recusa_arquivo_vazio(client: TestClient, headers):
    resp = _upload(client, headers, data=b"")
    assert resp.status_code == 422


def test_upload_recusa_acima_de_10mb(client: TestClient, headers):
    resp = _upload(client, headers, data=b"0" * (10 * 1024 * 1024 + 1))
    assert resp.status_code == 413


def test_bandeja_tem_teto_de_30(client: TestClient, headers):
    for _ in range(30):
        assert _upload(client, headers).status_code == 201
    resp = _upload(client, headers)
    assert resp.status_code == 409
    assert "bandeja" in resp.json()["detail"].lower()


def test_descartar_remove_da_bandeja(client: TestClient, headers):
    rid = _upload(client, headers).json()["id"]
    assert client.delete(f"/payables/receipts/{rid}", headers=headers).status_code == 204
    assert client.get("/payables/receipts", headers=headers).json() == []


def test_descartar_id_inexistente_da_404(client: TestClient, headers):
    assert client.delete("/payables/receipts/nao-existe", headers=headers).status_code == 404


def test_descartar_anexado_a_conta_da_409(client: TestClient, headers):
    """Um comprovante já linked a uma conta (owner_type != receipt_inbox) não pode ser descartado
    da bandeja — deve retornar 409."""
    # Upload um attachment via /attachments com owner_type="payable"
    resp = client.post(
        "/attachments",
        data={"owner_type": "payable", "owner_id": "bill-123", "label": "comprovante"},
        files={"file": ("comprovante.png", io.BytesIO(PNG), "image/png")},
        headers=headers,
    )
    assert resp.status_code == 201
    att_id = resp.json()["id"]

    # Tenta descartar via /payables/receipts (que espera owner_type=receipt_inbox)
    resp = client.delete(f"/payables/receipts/{att_id}", headers=headers)
    assert resp.status_code == 409
    assert "anexado" in resp.json()["detail"].lower()


def _bill(client: TestClient, headers, **over):
    base = {
        "description": "Energia",
        "category": "Estrutura",
        "supplier": "Copel",
        "amount_cents": 30000,
        "due_date": "2099-01-10",
    }
    return client.post("/payables/bills", json={**base, **over}, headers=headers).json()


def test_candidates_lista_abertas_por_vencimento(client: TestClient, headers):
    _bill(client, headers, description="Depois", due_date="2099-03-01")
    _bill(client, headers, description="Antes", due_date="2099-01-01")
    itens = client.get("/payables/receipts/candidates", headers=headers).json()
    assert [i["description"] for i in itens] == ["Antes", "Depois"]


def test_candidates_inclui_pagas_recentes_depois_das_abertas(client: TestClient, headers):
    aberta = _bill(client, headers, description="Aberta", due_date="2099-02-02")
    paga = _bill(client, headers, description="Paga", due_date="2099-02-03")
    client.post(f"/payables/bills/{paga['id']}/pay", headers=headers)
    itens = client.get("/payables/receipts/candidates", headers=headers).json()
    assert [i["description"] for i in itens] == ["Aberta", "Paga"]
    assert itens[0]["id"] == aberta["id"]


def test_candidates_nao_lista_canceladas(client: TestClient, headers):
    b = _bill(client, headers, description="Cancelada")
    client.post(f"/payables/bills/{b['id']}/cancel", headers=headers)
    itens = client.get("/payables/receipts/candidates", headers=headers).json()
    assert [i["description"] for i in itens] == []


def test_candidates_busca_por_descricao_e_fornecedor(client: TestClient, headers):
    _bill(client, headers, description="Aluguel sala", supplier="Imobiliária X")
    _bill(client, headers, description="Energia", supplier="Copel")

    por_descricao = client.get("/payables/receipts/candidates?q=aluguel", headers=headers).json()
    assert [i["description"] for i in por_descricao] == ["Aluguel sala"]

    por_fornecedor = client.get("/payables/receipts/candidates?q=copel", headers=headers).json()
    assert [i["description"] for i in por_fornecedor] == ["Energia"]
