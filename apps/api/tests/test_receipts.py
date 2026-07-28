"""Testes da bandeja de comprovantes (Contas a Pagar)."""
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
