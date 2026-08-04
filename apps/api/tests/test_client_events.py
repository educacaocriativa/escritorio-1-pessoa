"""Eventos narrativos gravados pelos caminhos que já existiam no CRM."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.modules.crm.models import ClientEvent

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


def _eventos(db, client_id: str) -> list[ClientEvent]:
    return list(
        db.scalars(
            select(ClientEvent)
            .where(ClientEvent.client_id == client_id)
            .order_by(ClientEvent.created_at, ClientEvent.id)
        ).all()
    )


def test_criar_cliente_grava_lead_created(client: TestClient, headers, db):
    resp = client.post(
        "/crm/clients", json={"name": "Flavio Kato", "phone": "(11) 99999-8888"},
        headers=headers,
    )
    assert resp.status_code == 201
    eventos = _eventos(db, resp.json()["id"])
    assert [e.kind for e in eventos] == ["lead_created"]
    assert eventos[0].title  # tem frase, não fica em branco


def test_criar_cliente_preenche_phone_key(client: TestClient, headers, db):
    """Sem isto o backfill conserta o legado e o código novo volta a criar linha sem chave."""
    from app.modules.crm.models import Client

    resp = client.post(
        "/crm/clients", json={"name": "Flavio Kato", "phone": "(11) 9999-8888"},
        headers=headers,
    )
    c = db.get(Client, resp.json()["id"])
    assert c.phone_key == "5511999998888"


def test_mover_card_grava_stage_move_com_nomes_congelados(client: TestClient, headers, db):
    criado = client.post("/crm/clients", json={"name": "Flavio Kato"}, headers=headers).json()
    cols = client.get("/crm/board", headers=headers).json()["columns"]
    proposta = next(c["stage"] for c in cols if c["stage"]["name"] == "Proposta")

    client.post(
        f"/crm/clients/{criado['id']}/move", json={"stage_id": proposta["id"]}, headers=headers
    )

    eventos = _eventos(db, criado["id"])
    assert [e.kind for e in eventos] == ["lead_created", "stage_move"]
    # o texto guarda os NOMES, não os ids — renomear a coluna depois não reescreve a história
    assert "Entrada" in eventos[1].title
    assert "Proposta" in eventos[1].title


def test_texto_do_evento_sobrevive_a_renomear_a_coluna(client: TestClient, headers, db):
    criado = client.post("/crm/clients", json={"name": "Flavio Kato"}, headers=headers).json()
    cols = client.get("/crm/board", headers=headers).json()["columns"]
    proposta = next(c["stage"] for c in cols if c["stage"]["name"] == "Proposta")
    client.post(
        f"/crm/clients/{criado['id']}/move", json={"stage_id": proposta["id"]}, headers=headers
    )

    client.patch(
        f"/crm/stages/{proposta['id']}", json={"name": "Negociação"}, headers=headers
    )

    eventos = _eventos(db, criado["id"])
    assert "Proposta" in eventos[1].title  # congelado: conta o que aconteceu naquele dia
