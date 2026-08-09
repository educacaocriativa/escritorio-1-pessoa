"""O contrato HTTP do DNA — incluindo quem NÃO pode responder."""
import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token

REGISTER = {
    "legal_name": "Vima ME",
    "document": "11444777000161",
    "slug": "vimame",
    "email": "vima@example.com",
    "name": "Flávio",
    "password": "uma-senha-bem-grande",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def tenant_id(client: TestClient, headers: dict[str, str]) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]


@pytest.fixture()
def headers_sub_crm(tenant_id: str) -> dict[str, str]:
    """Sub-usuário só de CRM: vê o briefing, mas o DNA é da EMPRESA e não é dele."""
    token = create_access_token(
        {
            "sub": "sub-crm",
            "tenant_id": tenant_id,
            "role": "member",
            "allowed_modules": ["comercial"],
        }
    )
    return {"Authorization": f"Bearer {token}"}


def test_nucleo_devolve_as_seis(client: TestClient, headers):
    corpo = client.get("/dna/faltantes", params={"gancho": "nucleo"}, headers=headers).json()
    assert len(corpo) == 6
    assert corpo[0]["key"] == "oferta.o_que_vende"
    assert corpo[0]["opcoes"][0]["rotulo"] == "Serviço recorrente"


def test_responder_e_ler_de_volta(client: TestClient, headers):
    r = client.put(
        "/dna/oferta.o_que_vende", json={"valor": "servico_projeto", "source": "nucleo"},
        headers=headers,
    )
    assert r.status_code == 200
    assert client.get("/dna/respostas", headers=headers).json()["oferta.o_que_vende"] == (
        "servico_projeto"
    )


def test_valor_invalido_devolve_400(client: TestClient, headers):
    r = client.put(
        "/dna/oferta.o_que_vende", json={"valor": "telepatia", "source": "config"},
        headers=headers,
    )
    assert r.status_code == 400


def test_chave_inexistente_devolve_404(client: TestClient, headers):
    r = client.put(
        "/dna/oferta.inventada", json={"valor": "x", "source": "config"}, headers=headers
    )
    assert r.status_code == 404


def test_pular_registra_sem_responder(client: TestClient, headers):
    assert client.post(
        "/dna/limites.nunca_faco/pular", json={"source": "gancho"}, headers=headers
    ).status_code == 200
    assert "limites.nunca_faco" not in client.get("/dna/respostas", headers=headers).json()


def test_pendente_por_gancho(client: TestClient, headers):
    corpo = client.get(
        "/dna/pendente",
        params={"gancho": "briefing.ausencia.comercial.card.parado"},
        headers=headers,
    ).json()
    assert corpo["key"] == "ritmo.card_parado_dias"


def test_dia_de_silencio_devolve_nulo(client: TestClient, headers):
    """Respondeu uma hoje: o gancho se cala até amanhã."""
    client.put(
        "/dna/oferta.o_que_vende", json={"valor": "misto", "source": "nucleo"}, headers=headers
    )
    corpo = client.get(
        "/dna/pendente",
        params={"gancho": "briefing.ausencia.comercial.card.parado"},
        headers=headers,
    ).json()
    assert corpo is None


def test_catalogo_devolve_as_45(client: TestClient, headers):
    """A aba de configurações é a única superfície SEM cadência."""
    corpo = client.get("/dna/catalogo", headers=headers).json()
    assert len(corpo) == 45


def test_sub_usuario_sem_settings_nao_alcanca_o_dna(client: TestClient, headers_sub_crm):
    """O DNA é da EMPRESA. Um sub-usuário recalibrando o negócio seria surpresa ruim."""
    assert client.get(
        "/dna/pendente", params={"gancho": "nucleo"}, headers=headers_sub_crm
    ).status_code == 403
    assert client.put(
        "/dna/oferta.o_que_vende", json={"valor": "misto", "source": "config"},
        headers=headers_sub_crm,
    ).status_code == 403
