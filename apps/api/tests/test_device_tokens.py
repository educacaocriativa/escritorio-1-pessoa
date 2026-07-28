"""Testes do token de dispositivo (credencial do Atalho do iOS)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.registry import Base  # noqa: F401 — garante o registro do modelo novo
from app.modules.device_tokens import service
from app.modules.device_tokens.models import SCOPE_RECEIPT_UPLOAD


@pytest.fixture()
def seeded(db: Session):
    return {"tenant_id": "t-1", "user_id": "u-1"}


def test_create_devolve_token_cru_e_guarda_so_o_hash(db: Session, seeded):
    token, raw = service.create_token(db, name="iPhone", **seeded)
    assert raw and len(raw) > 20
    assert token.token_hash != raw
    assert raw not in token.token_hash
    assert token.scope == SCOPE_RECEIPT_UPLOAD
    assert token.revoked_at is None


def test_resolve_encontra_pelo_token_cru_e_marca_uso(db: Session, seeded):
    _, raw = service.create_token(db, name="iPhone", **seeded)
    found = service.resolve(db, raw=raw, scope=SCOPE_RECEIPT_UPLOAD)
    assert found.user_id == "u-1"
    assert found.tenant_id == "t-1"
    assert found.last_used_at is not None


def test_resolve_recusa_token_desconhecido(db: Session, seeded):
    with pytest.raises(service.DeviceTokenError) as e:
        service.resolve(db, raw="nao-existe", scope=SCOPE_RECEIPT_UPLOAD)
    assert e.value.status_code == 401


def test_resolve_recusa_token_revogado(db: Session, seeded):
    token, raw = service.create_token(db, name="iPhone", **seeded)
    service.revoke(db, token_id=token.id, user_id="u-1")
    with pytest.raises(service.DeviceTokenError) as e:
        service.resolve(db, raw=raw, scope=SCOPE_RECEIPT_UPLOAD)
    assert e.value.status_code == 401


def test_resolve_recusa_escopo_diferente(db: Session, seeded):
    _, raw = service.create_token(db, name="iPhone", **seeded)
    with pytest.raises(service.DeviceTokenError) as e:
        service.resolve(db, raw=raw, scope="outro_escopo")
    assert e.value.status_code == 403


def test_revoke_de_outro_usuario_da_404(db: Session, seeded):
    token, _ = service.create_token(db, name="iPhone", **seeded)
    with pytest.raises(service.DeviceTokenError) as e:
        service.revoke(db, token_id=token.id, user_id="u-outro")
    assert e.value.status_code == 404


def test_list_traz_so_os_do_proprio_usuario(db: Session, seeded):
    service.create_token(db, name="iPhone", **seeded)
    service.create_token(db, tenant_id="t-1", user_id="u-2", name="Android")
    assert [t.name for t in service.list_tokens(db, user_id="u-1")] == ["iPhone"]


def test_list_omite_revogados(db: Session, seeded):
    token, _ = service.create_token(db, name="iPhone", **seeded)
    service.revoke(db, token_id=token.id, user_id="u-1")
    assert service.list_tokens(db, user_id="u-1") == []


REGISTER = {
    "legal_name": "Token Co",
    "document": "11444777000161",
    "slug": "tokenco",
    "email": "token@example.com",
    "name": "Token",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_criar_token_mostra_o_cru_uma_vez(client: TestClient, headers):
    resp = client.post("/settings/device-tokens", json={"name": "iPhone"}, headers=headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "iPhone"
    assert len(body["token"]) > 20

    # a listagem NUNCA devolve o token cru
    listagem = client.get("/settings/device-tokens", headers=headers).json()
    assert [t["name"] for t in listagem] == ["iPhone"]
    assert "token" not in listagem[0]


def test_revogar_some_da_listagem(client: TestClient, headers):
    tid = client.post(
        "/settings/device-tokens", json={"name": "iPhone"}, headers=headers
    ).json()["id"]
    assert client.delete(f"/settings/device-tokens/{tid}", headers=headers).status_code == 204
    assert client.get("/settings/device-tokens", headers=headers).json() == []


def test_rotas_exigem_login(client: TestClient):
    assert client.get("/settings/device-tokens").status_code == 401
