"""As três portas de entrada de contato convergem para o MESMO card."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.modules.crm import service as crm_service
from app.modules.crm.models import Client
from app.modules.crm.schemas import ClientCreate
from app.modules.whatsapp_inbox import service as inbox_service

REGISTER = {
    "legal_name": "Estúdio Ana",
    "document": "11222333000181",
    "slug": "estudioana",
    "email": "ana@example.com",
    "name": "Ana",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def tenant_id(client: TestClient) -> str:
    return client.post("/auth/register", json=REGISTER).json()["tenant"]["id"]


def test_site_depois_whatsapp_e_um_card_so(db, tenant_id):
    """O teste que amarra as duas portas.

    Sem a normalização compartilhada, o site guardaria "(11) 99999-8888", o WhatsApp
    guardaria "5511999998888", e a mesma pessoa continuaria virando dois cards — agora por
    um motivo mais difícil de enxergar do que o bug original.
    """
    crm_service.absorb_lead(
        db, tenant_id=tenant_id, actor="pagina:lead",
        data=ClientCreate(name="Flavio Kato", phone="(11) 99999-8888", source="landing"),
    )
    inbox_service._get_or_create_client(
        db, tenant_id=tenant_id, phone="5511999998888", name="Flavio",
    )

    assert db.scalar(select(func.count(Client.id))) == 1


def test_whatsapp_depois_site_e_um_card_so(db, tenant_id):
    inbox_service._get_or_create_client(
        db, tenant_id=tenant_id, phone="5511999998888", name="Flavio",
    )
    _, novo = crm_service.absorb_lead(
        db, tenant_id=tenant_id, actor="pagina:lead",
        data=ClientCreate(name="Flavio Kato", phone="(11) 99999-8888", source="landing"),
    )

    assert novo is False
    assert db.scalar(select(func.count(Client.id))) == 1


def test_whatsapp_grava_phone_key(db, tenant_id):
    contato = inbox_service._get_or_create_client(
        db, tenant_id=tenant_id, phone="5511999998888", name="Flavio",
    )
    assert contato.phone_key == "5511999998888"


@pytest.fixture()
def slug_publicado(client: TestClient) -> str:
    """Cria e publica uma página de captura, devolvendo o slug público.

    Contrato conferido em `tests/test_pages.py`: o corpo de criação usa `model` (não
    `template`), e o slug vem em `public_slug` na resposta da CRIAÇÃO — `publish` só torna
    a página visível.
    """
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    page = client.post(
        "/pages", json={"title": "Captura", "model": "captura"}, headers=h
    ).json()
    client.post(f"/pages/{page['id']}/publish", headers=h)
    return page["public_slug"]


def test_formulario_publico_repetido_nao_duplica(client: TestClient, slug_publicado, db):
    """Envio duplicado pelo formulário da landing page — o bug original da tela do fundador."""
    corpo = {"name": "Flavio Kato", "phone": "(11) 99999-8888", "email": "f@example.com"}
    assert client.post(f"/public/pages/{slug_publicado}/submit", json=corpo).status_code < 400
    assert client.post(f"/public/pages/{slug_publicado}/submit", json=corpo).status_code < 400

    assert db.scalar(select(func.count(Client.id))) == 1
