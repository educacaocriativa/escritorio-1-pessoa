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


def _card_do_board(client: TestClient, headers, client_id: str) -> dict:
    cols = client.get("/crm/board", headers=headers).json()["columns"]
    return next(c for col in cols for c in col["clients"] if c["id"] == client_id)


def test_board_traz_a_data_da_ultima_interacao(client: TestClient, headers):
    criado = client.post("/crm/clients", json={"name": "Flavio Kato"}, headers=headers).json()
    card = _card_do_board(client, headers, criado["id"])
    # já existe o lead_created, então a data nunca vem vazia para contato criado pelo app
    assert card["last_interaction_at"] is not None


def test_data_da_ultima_interacao_avanca_com_o_movimento(client: TestClient, headers):
    criado = client.post("/crm/clients", json={"name": "Flavio Kato"}, headers=headers).json()
    antes = _card_do_board(client, headers, criado["id"])["last_interaction_at"]

    cols = client.get("/crm/board", headers=headers).json()["columns"]
    proposta = next(c["stage"] for c in cols if c["stage"]["name"] == "Proposta")
    client.post(
        f"/crm/clients/{criado['id']}/move", json={"stage_id": proposta["id"]}, headers=headers
    )

    depois = _card_do_board(client, headers, criado["id"])["last_interaction_at"]
    assert depois >= antes
