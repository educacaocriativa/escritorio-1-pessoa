"""Testes do caminho S3 dos Anexos (Story 3.5).

O object storage é MOCKADO (dict em memória) — sem rede, sem credenciais, sem bucket real em
CI. Cobre: upload grava storage_key (e não data), download resolve via storage, delete chama o
storage, anexo legado (data setado) continua baixando mesmo com storage "ligado", e o
isolamento por tenant no path (`build_key`).
"""
import io

import pytest
from fastapi.testclient import TestClient

from app.core import storage

REGISTER = {
    "legal_name": "Anexo S3 SA",
    "document": "51515151000113",
    "slug": "anexos3",
    "email": "anexos3@example.com",
    "name": "An3",
    "password": "senha-bem-comprida",
}


class FakeStorage:
    """Fake do object storage: guarda os bytes num dict {key: (data, content_type)}."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.deleted: list[str] = []

    def is_configured(self) -> bool:
        return True

    def build_key(self, tenant_id: str, attachment_id: str, filename: str) -> str:
        # Reusa a implementação real (é a lógica sob teste de isolamento por path).
        return storage.build_key(tenant_id, attachment_id, filename)

    def put_object(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    def get_object(self, key: str) -> bytes:
        return self.objects[key][0]

    def delete_object(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)


@pytest.fixture()
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> FakeStorage:
    fake = FakeStorage()
    # O service acessa `storage.<func>` (atributos do módulo) — patch nos atributos do módulo.
    monkeypatch.setattr(storage, "is_configured", fake.is_configured)
    monkeypatch.setattr(storage, "put_object", fake.put_object)
    monkeypatch.setattr(storage, "get_object", fake.get_object)
    monkeypatch.setattr(storage, "delete_object", fake.delete_object)
    return fake


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _upload(client, headers, *, content=b"%PDF-1.4 s3", name="boleto.pdf",
            ctype="application/pdf", owner_type="payable", owner_id="p1", label="boleto"):
    return client.post(
        "/attachments",
        data={"owner_type": owner_type, "owner_id": owner_id, "label": label},
        files={"file": (name, io.BytesIO(content), ctype)},
        headers=headers,
    )


def test_upload_goes_to_storage_not_postgres(client, headers, fake_storage, db):
    from app.modules.attachments.models import Attachment

    resp = _upload(client, headers, content=b"%PDF s3 bytes")
    assert resp.status_code == 201, resp.text
    att_id = resp.json()["id"]
    # A linha no banco NÃO deve ter os bytes; deve ter uma storage_key; os bytes vivem no fake.
    row = db.get(Attachment, att_id)
    assert row.data is None
    assert row.storage_key is not None
    assert row.storage_key in fake_storage.objects
    assert fake_storage.objects[row.storage_key][0] == b"%PDF s3 bytes"


def test_download_resolves_from_storage(client, headers, fake_storage):
    _upload(client, headers, owner_id="charge-9", owner_type="charge", content=b"%PDF do s3")
    lst = client.get("/attachments?owner_type=charge&owner_id=charge-9", headers=headers).json()
    att_id = lst[0]["id"]
    dl = client.get(f"/attachments/{att_id}/download", headers=headers)
    assert dl.status_code == 200
    assert dl.content == b"%PDF do s3"


def test_delete_removes_from_storage(client, headers, fake_storage, db):
    from app.modules.attachments.models import Attachment

    a = _upload(client, headers).json()
    row = db.get(Attachment, a["id"])
    key = row.storage_key
    assert client.delete(f"/attachments/{a['id']}", headers=headers).status_code == 204
    assert key in fake_storage.deleted


def test_legacy_attachment_still_downloads_with_storage_on(client, headers, fake_storage, db):
    """Anexo pré-migração (data setado, storage_key=None) continua baixando mesmo com o storage
    ligado — cobre AC3/IV1 (download de anexos antigos não quebra)."""
    from app.modules.attachments.models import Attachment

    legacy = Attachment(
        tenant_id="00000000-legacy-tenant", owner_type="payable", owner_id="leg",
        label="boleto", filename="antigo.pdf", content_type="application/pdf",
        size=11, data=b"%PDF legacy", storage_key=None,
    )
    db.add(legacy)
    db.commit()
    dl = client.get(f"/attachments/{legacy.id}/download", headers=headers)
    assert dl.status_code == 200
    assert dl.content == b"%PDF legacy"
    # Não tocou no storage (bytes vieram do Postgres).
    assert legacy.id not in fake_storage.objects


def test_build_key_isolates_by_tenant():
    """Dois tenants geram chaves distintas, cada uma prefixada pelo próprio tenant_id (IV2)."""
    k1 = storage.build_key("tenant-aaaa", "att-1", "boleto.pdf")
    k2 = storage.build_key("tenant-bbbb", "att-1", "boleto.pdf")
    assert k1 != k2
    assert k1.startswith("tenants/tenant-aaaa/")
    assert k2.startswith("tenants/tenant-bbbb/")
    assert k1.endswith("/boleto.pdf")


def test_build_key_sanitizes_filename():
    """Nomes com separadores de path não escapam do prefixo do tenant."""
    key = storage.build_key("tenant-xxxx", "att-9", "../../etc/passwd")
    assert key.startswith("tenants/tenant-xxxx/attachments/att-9/")
    assert "/../" not in key
