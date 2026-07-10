"""Testes de Anexos: upload, validação de tipo/tamanho, listagem, download e remoção."""
import io

import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Anexo SA",
    "document": "51515151000113",
    "slug": "anexosa",
    "email": "anexo@example.com",
    "name": "An",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _upload(client, headers, *, content=b"%PDF-1.4 fake", name="boleto.pdf",
            ctype="application/pdf", owner_type="payable", owner_id="p1", label="boleto"):
    return client.post(
        "/attachments",
        data={"owner_type": owner_type, "owner_id": owner_id, "label": label},
        files={"file": (name, io.BytesIO(content), ctype)},
        headers=headers,
    )


def test_upload_pdf(client: TestClient, headers):
    resp = _upload(client, headers)
    assert resp.status_code == 201, resp.text
    a = resp.json()
    assert a["filename"] == "boleto.pdf"
    assert a["content_type"] == "application/pdf"
    assert a["label"] == "boleto"
    assert a["size"] > 0


def test_reject_disallowed_type(client: TestClient, headers):
    resp = _upload(client, headers, name="x.txt", ctype="text/plain")
    assert resp.status_code == 415


def test_list_by_owner_and_download(client: TestClient, headers):
    _upload(client, headers, owner_id="charge-1", owner_type="charge", label="contrato",
            content=b"%PDF contrato", name="contrato.pdf")
    lst = client.get("/attachments?owner_type=charge&owner_id=charge-1", headers=headers).json()
    assert len(lst) == 1
    att_id = lst[0]["id"]
    dl = client.get(f"/attachments/{att_id}/download", headers=headers)
    assert dl.status_code == 200
    assert dl.content == b"%PDF contrato"
    assert dl.headers["content-type"].startswith("application/pdf")


def test_owner_filter_isolated(client: TestClient, headers):
    _upload(client, headers, owner_id="A")
    _upload(client, headers, owner_id="B")
    only_a = client.get("/attachments?owner_type=payable&owner_id=A", headers=headers).json()
    assert len(only_a) == 1


def test_delete(client: TestClient, headers):
    a = _upload(client, headers).json()
    assert client.delete(f"/attachments/{a['id']}", headers=headers).status_code == 204
    assert client.get(f"/attachments/{a['id']}/download", headers=headers).status_code == 404


def test_requires_auth(client: TestClient):
    assert client.get("/attachments?owner_type=payable&owner_id=x").status_code == 401


# ── Imagens públicas (Story 4.2) ─────────────────────────────────────────────
_PNG = b"\x89PNG\r\n\x1a\n fake png bytes"


def _upload_public_image(client, headers, *, content=_PNG, name="logo.png", ctype="image/png"):
    return client.post(
        "/attachments/public-images",
        files={"file": (name, io.BytesIO(content), ctype)},
        headers=headers,
    )


def test_public_image_upload_returns_url(client: TestClient, headers):
    resp = _upload_public_image(client, headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"]
    # URL relativa da rota de leitura no backend (frontend prefixa o proxy /api).
    assert body["url"] == f"/public-images/{body['id']}"


def test_public_image_rejects_non_image_type(client: TestClient, headers):
    # PDF é permitido em Attachment, mas NÃO nas imagens públicas (só JPEG/PNG).
    resp = _upload_public_image(client, headers, content=b"%PDF-1.4", name="x.pdf",
                                ctype="application/pdf")
    assert resp.status_code == 415


def test_public_image_rejects_oversize(client: TestClient, headers):
    big = b"\x89PNG" + b"0" * (10 * 1024 * 1024 + 1)
    resp = _upload_public_image(client, headers, content=big)
    assert resp.status_code == 413


def test_public_image_served_without_auth(client: TestClient, headers):
    up = _upload_public_image(client, headers).json()
    # Leitura pública: SEM header Authorization → 200 com os bytes/tipo corretos.
    dl = client.get(up["url"])
    assert dl.status_code == 200
    assert dl.content == _PNG
    assert dl.headers["content-type"] == "image/png"
    # Sem Content-Disposition: attachment (renderiza inline em <img>).
    assert "attachment" not in dl.headers.get("content-disposition", "")


def test_public_image_upload_requires_auth(client: TestClient):
    resp = client.post(
        "/attachments/public-images",
        files={"file": ("logo.png", io.BytesIO(_PNG), "image/png")},
    )
    assert resp.status_code == 401


def test_public_image_not_found(client: TestClient):
    assert client.get("/public-images/does-not-exist").status_code == 404
