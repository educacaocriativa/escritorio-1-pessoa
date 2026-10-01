"""`POST /public/ingest/leads`: credencial, contrato de status (201/200/401/422) e CORS."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.crm.models import Client
from app.modules.device_tokens import service as device_tokens_service
from app.modules.machine_tokens import service as machine_tokens_service
from app.modules.machine_tokens.models import SCOPE_LEAD_INGEST
from tests.lead_ingest_apoio import corpo

URL = "/public/ingest/leads"
REGISTER = {
    "legal_name": "Nexus Pública",
    "document": "11222333000181",
    "slug": "nexus",
    "email": "dono@nexus.example.com",
    "name": "Dono",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def cadastro(client: TestClient) -> dict:
    return client.post("/auth/register", json=REGISTER).json()


@pytest.fixture()
def tenant_id(cadastro: dict) -> str:
    return cadastro["tenant"]["id"]


@pytest.fixture()
def credencial(db: Session, tenant_id: str) -> dict[str, str]:
    _, raw = machine_tokens_service.create_token(
        db, tenant_id=tenant_id, name="site", scope=SCOPE_LEAD_INGEST
    )
    return {"Authorization": f"Bearer {raw}"}


def test_primeiro_envio_201_e_repetido_200(client: TestClient, credencial, db, tenant_id):
    primeiro = client.post(URL, json=corpo(), headers=credencial)
    assert primeiro.status_code == 201, primeiro.text
    assert primeiro.json()["resultado"] == "processado"
    contato = db.get(Client, primeiro.json()["contato_id"])
    assert contato.tenant_id == tenant_id
    assert contato.source == "api"

    repetido = client.post(URL, json=corpo(), headers=credencial)
    assert repetido.status_code == 200
    assert repetido.json() == {"resultado": "ja_processado", "contato_id": contato.id}


def test_tenant_vem_do_token_nunca_do_corpo(client: TestClient, credencial, db, tenant_id):
    resp = client.post(URL, json=corpo(tenant_id="outro-tenant-qualquer-123"), headers=credencial)
    assert resp.status_code == 201
    assert db.get(Client, resp.json()["contato_id"]).tenant_id == tenant_id


@pytest.mark.parametrize("cabecalho", [None, "Bearer nao-existe", "Token abc", "bearer"])
def test_credencial_ausente_ou_invalida_401(client: TestClient, tenant_id, cabecalho):
    headers = {} if cabecalho is None else {"Authorization": cabecalho}
    assert client.post(URL, json=corpo(), headers=headers).status_code == 401


def test_credencial_revogada_401(client: TestClient, db, tenant_id):
    token, raw = machine_tokens_service.create_token(
        db, tenant_id=tenant_id, name="site", scope=SCOPE_LEAD_INGEST
    )
    machine_tokens_service.revoke(db, token_id=token.id)
    resp = client.post(URL, json=corpo(), headers={"Authorization": f"Bearer {raw}"})
    assert resp.status_code == 401


def test_token_de_dispositivo_nao_abre_a_ingestao(client: TestClient, db, tenant_id):
    _, raw = device_tokens_service.create_token(
        db, tenant_id=tenant_id, user_id="u-1", name="iPhone"
    )
    resp = client.post(URL, json=corpo(), headers={"Authorization": f"Bearer {raw}"})
    assert resp.status_code == 401


def test_jwt_do_dono_nao_abre_a_ingestao(client: TestClient, cadastro):
    headers = {"Authorization": f"Bearer {cadastro['access_token']}"}
    assert client.post(URL, json=corpo(), headers=headers).status_code == 401


def test_credencial_e_conferida_antes_do_corpo(client: TestClient, tenant_id):
    resp = client.post(
        URL, json={"evento": "nao-existe"}, headers={"Authorization": "Bearer nao-existe"}
    )
    assert resp.status_code == 401


def test_corpo_invalido_com_credencial_valida_422(client: TestClient, credencial):
    resp = client.post(URL, json=corpo(contato={"nome": "Sem Canal"}), headers=credencial)
    assert resp.status_code == 422


def test_rota_removida_no_270_nao_volta_com_cors_aberto(client: TestClient):
    resp = client.post(
        "/public/leads/qualquer", json={}, headers={"Origin": "https://site-qualquer.example"}
    )
    assert resp.status_code in (404, 405)
    assert "access-control-allow-origin" not in resp.headers


def test_ingestao_nao_tem_cors_para_navegador(client: TestClient):
    resp = client.options(
        URL,
        headers={
            "Origin": "https://nexuspublica.com.br",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.headers.get("access-control-allow-origin") != "https://nexuspublica.com.br"


def test_corpo_acima_de_64kb_413_e_nada_gravado(client: TestClient, credencial, db):
    antes = db.query(Client).count()
    grande = corpo(contato={"nome": "X" * (65 * 1024), "email": "a@b.example"})
    resp = client.post(URL, json=grande, headers=credencial)
    assert resp.status_code == 413
    assert db.query(Client).count() == antes


def test_corpo_acima_de_64kb_sem_content_length_413(client: TestClient, credencial):
    def pedacos():
        for _ in range(65):
            yield b"x" * 1024
        yield b"x" * 1024

    resp = client.post(
        URL, content=pedacos(), headers={**credencial, "Content-Type": "application/json"}
    )
    assert resp.status_code == 413


def test_corpo_normal_nao_e_afetado_pelo_limite(client: TestClient, credencial):
    assert client.post(URL, json=corpo(), headers=credencial).status_code == 201
