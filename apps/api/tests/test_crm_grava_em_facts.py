"""O CRM grava em `facts`, com module='crm' e a taxonomia nova."""
import pytest
from fastapi.testclient import TestClient

from app.core.facts import (
    CRM_ETAPA_MOVIDA,
    CRM_LEAD_CRIADO,
    CRM_NOTA_CRIADA,
    Fact,
)

REGISTER = {
    "legal_name": "Estúdio Ana", "document": "11222333000181", "slug": "estudioana",
    "email": "ana@example.com", "name": "Ana", "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_criar_contato_grava_fato_de_crm(client: TestClient, headers, db):
    client.post("/crm/clients", json={"name": "Flavio Kato"}, headers=headers)
    fatos = db.query(Fact).all()
    assert len(fatos) == 1
    assert fatos[0].module == "crm"
    assert fatos[0].kind == CRM_LEAD_CRIADO
    assert fatos[0].client_id is not None
    # `subject_type`/`subject_id` apontam para o contato: é o sujeito do fato, e o briefing
    # (Onda 3) resolve o valor pela dupla, não pelo `client_id`.
    assert fatos[0].subject_type == "client"
    assert fatos[0].subject_id == fatos[0].client_id


def test_mover_card_grava_fato(client: TestClient, headers, db):
    contato = client.post(
        "/crm/clients", json={"name": "Flavio Kato"}, headers=headers
    ).json()["id"]
    cols = client.get("/crm/board", headers=headers).json()["columns"]
    destino = next(c["stage"] for c in cols if c["stage"]["name"] == "Proposta")["id"]
    client.post(
        f"/crm/clients/{contato}/move", json={"stage_id": destino}, headers=headers
    )

    kinds = [f.kind for f in db.query(Fact).order_by(Fact.created_at).all()]
    assert kinds == [CRM_LEAD_CRIADO, CRM_ETAPA_MOVIDA]


def test_anotacao_do_dono_grava_fato(client: TestClient, headers, db):
    contato = client.post(
        "/crm/clients", json={"name": "Flavio Kato"}, headers=headers
    ).json()["id"]
    client.post(
        f"/crm/clients/{contato}/notes",
        json={"title": "Desconto", "body": "combinei R$ 500 de entrada"},
        headers=headers,
    )

    nota = db.query(Fact).filter(Fact.kind == CRM_NOTA_CRIADA).one()
    # O `body` é texto do usuário e PODE conter dinheiro — são as palavras dele, não uma
    # segunda fonte de verdade. A Invariante 2 vale para o `title`, gerado pelo sistema.
    assert "R$ 500" in nota.body
