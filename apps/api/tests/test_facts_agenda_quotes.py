"""Agenda e orçamentos gravam fato.

`quotes` emite sob `module="comercial"`, não `module="quotes"`: o prefixo é o vocabulário de
`User.allowed_modules` — o que o dono vê na tela de permissões —, não o nome da pasta.
"""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.facts import (
    AGENDA_EVENTO_CANCELADO,
    AGENDA_EVENTO_REMARCADO,
    COM_ORCAMENTO_ACEITO,
    COM_ORCAMENTO_ENVIADO,
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


def _evento(client: TestClient, headers) -> dict:
    inicio = datetime.now(UTC) + timedelta(days=3)
    return client.post(
        "/agenda/events",
        json={
            "title": "Reunião com Maria", "kind": "atendimento",
            "starts_at": inicio.isoformat(),
            "ends_at": (inicio + timedelta(hours=1)).isoformat(),
        },
        headers=headers,
    ).json()["event"]


def test_cancelar_evento_grava_fato(client: TestClient, headers, db):
    evento = _evento(client, headers)
    client.post(f"/agenda/events/{evento['id']}/cancel", headers=headers)

    fato = db.query(Fact).filter(Fact.kind == AGENDA_EVENTO_CANCELADO).one()
    assert fato.module == "agenda"
    assert fato.subject_type == "agenda_event"
    assert fato.subject_id == evento["id"]
    assert "Reunião com Maria" in fato.title


def test_remarcar_evento_grava_fato(client: TestClient, headers, db):
    evento = _evento(client, headers)
    novo = datetime.now(UTC) + timedelta(days=5)
    client.post(
        f"/agenda/events/{evento['id']}/reschedule",
        json={
            "starts_at": novo.isoformat(),
            "ends_at": (novo + timedelta(hours=1)).isoformat(),
        },
        headers=headers,
    )

    fato = db.query(Fact).filter(Fact.kind == AGENDA_EVENTO_REMARCADO).one()
    assert fato.module == "agenda"
    assert "Reunião com Maria" in fato.title


def test_orcamento_enviado_e_aceito_gravam_fato_sem_valor(client: TestClient, headers, db):
    contato = client.post(
        "/crm/clients", json={"name": "Flavio Kato"}, headers=headers
    ).json()["id"]
    orcamento = client.post(
        "/quotes",
        json={
            "client_id": contato, "title": "Consultoria tributária",
            "items": [{"description": "Hora técnica", "quantity": 10, "unit_price_cents": 20000}],
        },
        headers=headers,
    ).json()

    client.post(f"/quotes/{orcamento['id']}/send", headers=headers)
    client.post(f"/quotes/{orcamento['id']}/approve", headers=headers)

    enviado = db.query(Fact).filter(Fact.kind == COM_ORCAMENTO_ENVIADO).one()
    aceito = db.query(Fact).filter(Fact.kind == COM_ORCAMENTO_ACEITO).one()

    for fato in (enviado, aceito):
        assert fato.module == "comercial"
        assert fato.subject_type == "quote"
        assert fato.client_id == contato
        assert "Consultoria tributária" in fato.title
        # Invariante 2 — o total de R$ 2.000,00 fica em `quotes`, lido na composição.
        assert "R$" not in fato.title


def test_aprovar_orcamento_grava_o_fato_antes_do_efeito_domino(client: TestClient, headers, db):
    """O aceite precede a cobrança que ele gera — a ordem conta a causalidade na timeline."""
    from app.core.facts import FIN_PAGAMENTO_RECEBIDO  # noqa: F401  (documenta o contraste)

    contato = client.post(
        "/crm/clients", json={"name": "Flavio Kato"}, headers=headers
    ).json()["id"]
    orcamento = client.post(
        "/quotes",
        json={
            "client_id": contato, "title": "Projeto",
            "items": [{"description": "Escopo", "quantity": 1, "unit_price_cents": 500000}],
        },
        headers=headers,
    ).json()
    client.post(f"/quotes/{orcamento['id']}/approve", headers=headers)

    kinds = [
        f.kind for f in db.query(Fact).order_by(Fact.created_at).all()
        if f.client_id == contato
    ]
    assert kinds.index(COM_ORCAMENTO_ACEITO) > 0  # depois do lead_created
