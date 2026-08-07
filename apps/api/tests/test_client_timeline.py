"""Timeline do contato: mescla o narrativo (`facts`) com o financeiro (charges/quotes)."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core.facts import Fact

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


@pytest.fixture()
def contato(client: TestClient, headers) -> str:
    return client.post(
        "/crm/clients", json={"name": "Flavio Kato", "phone": "(11) 99999-8888"},
        headers=headers,
    ).json()["id"]


def test_timeline_comeca_com_a_chegada(client: TestClient, headers, contato):
    resp = client.get(f"/crm/clients/{contato}/timeline", headers=headers)
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["truncated"] is False
    assert [e["kind"] for e in corpo["entries"]] == ["crm.lead.criado"]


def test_timeline_inclui_a_cobranca_sem_copiar_o_valor(client: TestClient, headers, contato, db):
    """O financeiro é LIDO de `charges`. Nenhuma linha de `facts` guarda o valor.

    A cobrança é semeada direto no banco (e não pela rota) de propósito: o contrato de
    `POST /receivables/charges` não é definido por este plano, e o que está sendo provado
    aqui é o read model da timeline, não a criação de cobrança.
    """
    from sqlalchemy import select

    from app.modules.crm.models import Client
    from app.modules.receivables.models import Charge

    tenant_id = db.scalar(select(Client.tenant_id).where(Client.id == contato))
    db.add(
        Charge(
            tenant_id=tenant_id, client_id=contato, description="Ensaio",
            kind="service", method="pix", amount_cents=120000,
            due_date=date(2026, 9, 10),
        )
    )
    db.commit()

    corpo = client.get(f"/crm/clients/{contato}/timeline", headers=headers).json()
    entrada = next(e for e in corpo["entries"] if e["kind"] == "charge")
    assert "1.200,00" in entrada["title"]

    # A fonte única do valor continua sendo `charges`: nenhum evento narrativo o copiou.
    eventos = list(
        db.scalars(select(Fact).where(Fact.client_id == contato)).all()
    )
    assert all("1.200,00" not in (e.title + e.body) for e in eventos)


def test_timeline_ordena_do_mais_recente_para_o_mais_antigo(client: TestClient, headers, contato):
    cols = client.get("/crm/board", headers=headers).json()["columns"]
    proposta = next(c["stage"] for c in cols if c["stage"]["name"] == "Proposta")
    client.post(f"/crm/clients/{contato}/move", json={"stage_id": proposta["id"]}, headers=headers)

    entries = client.get(f"/crm/clients/{contato}/timeline", headers=headers).json()["entries"]
    ats = [e["at"] for e in entries]
    assert ats == sorted(ats, reverse=True)
    assert entries[-1]["kind"] == "crm.lead.criado"  # o mais antigo é a chegada


def test_gravar_nota_aparece_na_timeline(client: TestClient, headers, contato):
    resp = client.post(
        f"/crm/clients/{contato}/notes",
        json={"title": "Desconto aprovado", "body": "Cliente pediu 10%, fechamos em 10%"},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["kind"] == "crm.nota.criada"

    entries = client.get(f"/crm/clients/{contato}/timeline", headers=headers).json()["entries"]
    nota = next(e for e in entries if e["kind"] == "crm.nota.criada")
    assert nota["title"] == "Desconto aprovado"
    assert "10%" in nota["body"]


def test_nota_sem_titulo_e_rejeitada(client: TestClient, headers, contato):
    resp = client.post(f"/crm/clients/{contato}/notes", json={"title": "  "}, headers=headers)
    assert resp.status_code == 422


def test_timeline_de_contato_inexistente_da_404(client: TestClient, headers):
    assert client.get("/crm/clients/nao-existe/timeline", headers=headers).status_code == 404


def test_truncated_quando_passa_do_teto(client: TestClient, headers, contato):
    for i in range(101):
        client.post(
            f"/crm/clients/{contato}/notes", json={"title": f"nota {i}"}, headers=headers
        )
    corpo = client.get(f"/crm/clients/{contato}/timeline", headers=headers).json()
    assert corpo["truncated"] is True
    assert len(corpo["entries"]) == 100
