"""Topo do funil: qual página converteu — e a jornada que quebra em silêncio."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.facts import COM_FORMULARIO_RECEBIDO, CRM_LEAD_CRIADO, OP_JORNADA_FALHOU, Fact
from app.modules.auth.models import Tenant

REGISTER = {
    "legal_name": "Estúdio Ana", "document": "11222333000181", "slug": "estudioana",
    "email": "ana@example.com", "name": "Ana", "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_formulario_grava_fato_com_a_pagina_de_origem(client: TestClient, headers, db):
    """DOIS fatos para UM acontecimento, de propósito.

    `crm.lead.criado` diz que o contato nasceu; `comercial.formulario.recebido` diz QUAL
    PÁGINA converteu. São informações diferentes, e o compositor do briefing (Onda 3) é quem
    as funde numa frase — o log guarda as duas.
    """
    pagina = client.post(
        "/pages",
        json={"title": "Consultoria Tributária", "template": "captura"},
        headers=headers,
    ).json()
    client.post(f"/pages/{pagina['id']}/publish", headers=headers)
    slug = client.get(f"/pages/{pagina['id']}", headers=headers).json()["public_slug"]

    client.post(
        f"/public/pages/{slug}/submit",
        json={"name": "Maria", "email": "maria@example.com", "phone": "(11) 98888-7777"},
    )

    formulario = db.query(Fact).filter(Fact.kind == COM_FORMULARIO_RECEBIDO).one()
    assert formulario.module == "comercial"
    assert formulario.subject_type == "page"
    assert formulario.subject_id == pagina["id"]
    assert "Consultoria Tributária" in formulario.title
    assert formulario.client_id is not None

    # O outro fato continua existindo — o colapso é da composição, não do log.
    lead = db.query(Fact).filter(Fact.kind == CRM_LEAD_CRIADO).one()
    assert lead.client_id == formulario.client_id


def test_jornada_que_falha_grava_fato(client: TestClient, headers, db):
    """Hoje a `run` fica `failed` e ninguém é avisado: a automação para de funcionar em
    silêncio, e o dono descobre semanas depois porque um cliente reclamou."""
    from app.modules.funnels import engine
    from app.modules.funnels.models import Funnel

    tenant_id = db.scalar(select(Tenant.id))
    contato = client.post(
        "/crm/clients", json={"name": "Flavio Kato"}, headers=headers
    ).json()["id"]

    # Funil com um nó que aponta para um destino inexistente — um dos quatro caminhos de falha.
    funil = Funnel(
        tenant_id=tenant_id, name="Pós-proposta",
        nodes=[{"id": "n1", "data": {"key": "anotacao", "label": "Início", "config": {}}}],
        edges=[{"id": "e1", "source": "n1", "target": "fantasma"}],
    )
    db.add(funil)
    db.commit()

    engine.enroll(db, tenant_id=tenant_id, actor="teste", funnel_id=funil.id, client_id=contato)
    db.commit()

    fatos = db.query(Fact).filter(Fact.kind == OP_JORNADA_FALHOU).all()
    assert len(fatos) == 1
    assert fatos[0].module == "operacao"
    assert fatos[0].subject_type == "funnel_run"
    assert "Pós-proposta" in fatos[0].title
    assert fatos[0].body  # o motivo da falha vai no corpo
