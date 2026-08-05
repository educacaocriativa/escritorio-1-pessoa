"""Ordem de entrada na etapa: a fila FIFO de cada coluna do Kanban.

Spec: docs/superpowers/specs/2026-08-05-crm-ordem-de-entrada-na-etapa-design.md
"""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

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


def test_cliente_novo_nasce_carimbado(client: TestClient, headers, db):
    """Todo card sabe desde quando está na etapa em que está."""
    from app.modules.crm.models import Client

    antes = datetime.now(UTC) - timedelta(seconds=5)
    resp = client.post("/crm/clients", json={"name": "João"}, headers=headers)
    assert resp.status_code == 201

    row = db.get(Client, resp.json()["id"])
    assert row.stage_entered_at is not None
    # SQLite devolve naive; comparamos em UTC consciente.
    carimbo = row.stage_entered_at
    if carimbo.tzinfo is None:
        carimbo = carimbo.replace(tzinfo=UTC)
    assert carimbo >= antes


def _stage_ids(client: TestClient, headers) -> list[str]:
    return [s["id"] for s in client.get("/crm/stages", headers=headers).json()]


# Um instante do passado, longe o bastante para que "recarimbou" e "não recarimbou" sejam
# distinguíveis SEM depender da resolução do relógio. Uma asserção `depois >= antes` sobre o
# carimbo natural é satisfeita por IGUALDADE — ou seja, passa mesmo sem implementação nenhuma,
# que é exatamente o teste que não testa nada.
PASSADO = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)


def _carimbo(db, client_id: str) -> datetime:
    """Lê o carimbo sempre como UTC consciente (o SQLite dos testes devolve naive)."""
    from app.modules.crm.models import Client

    db.expire_all()
    valor = db.get(Client, client_id).stage_entered_at
    return valor.replace(tzinfo=UTC) if valor.tzinfo is None else valor


def _envelhecer(db, client_id: str) -> None:
    """Empurra o carimbo para o passado, para que um recarimbo seja inequívoco."""
    from app.modules.crm.models import Client

    db.get(Client, client_id).stage_entered_at = PASSADO
    db.commit()


def test_mover_card_recarimba(client: TestClient, headers, db):
    """Mudar de coluna é entrar numa etapa nova: o card vai para o fim da fila de destino."""
    from app.modules.crm.models import Client

    stages = _stage_ids(client, headers)
    criado = client.post("/crm/clients", json={"name": "João"}, headers=headers).json()
    _envelhecer(db, criado["id"])

    resp = client.post(
        f"/crm/clients/{criado['id']}/move", json={"stage_id": stages[1]}, headers=headers
    )
    assert resp.status_code == 200

    assert _carimbo(db, criado["id"]) > PASSADO
    assert db.get(Client, criado["id"]).stage_id == stages[1]


def test_arquivar_etapa_preserva_antiguidade(client: TestClient, headers, db):
    """Arquivar é ato administrativo do dono — não custa a vez de quem esperou mais.

    Se recarimbasse, todo card da coluna arquivada iria em bloco para o fim da fila de
    destino, e a fila que existe para atender por antiguidade puniria quem esperou mais.
    """
    from app.modules.crm.models import Client

    stages = _stage_ids(client, headers)
    criado = client.post(
        "/crm/clients", json={"name": "Antigo", "stage_id": stages[2]}, headers=headers
    ).json()
    _envelhecer(db, criado["id"])

    # Arquivar é POST .../archive (204). `DELETE /crm/stages/{id}` é outra coisa: recusa com
    # 409 quando a etapa tem clientes, então não exercitaria o remanejamento nenhum.
    resp = client.post(f"/crm/stages/{stages[2]}/archive", headers=headers)
    assert resp.status_code == 204

    assert db.get(Client, criado["id"]).stage_id == stages[0]  # remanejado p/ a primeira ativa
    assert _carimbo(db, criado["id"]) == PASSADO               # antiguidade INTACTA


def test_reabertura_recarimba(client: TestClient, headers, db):
    """Retorno em coluna terminal reabre o card — e reabrir é entrar numa etapa nova.

    A reabertura escreve `stage_id` por um caminho DIFERENTE do `move_client` e grava
    `reopened` em vez de `stage_move` — é exatamente por isso que a ordem não pode ser
    derivada de `client_events` filtrando um kind só.
    """
    from app.modules.crm import service
    from app.modules.crm.models import PipelineStage
    from app.modules.crm.schemas import ClientCreate

    stages = _stage_ids(client, headers)
    tenant_id = db.scalars(select(PipelineStage)).first().tenant_id

    # Nasce direto na coluna terminal "Perda" (a última do seed padrão).
    perdido = client.post(
        "/crm/clients",
        json={"name": "Voltou", "phone": "11999998888", "stage_id": stages[-1]},
        headers=headers,
    ).json()
    _envelhecer(db, perdido["id"])

    existente, novo = service.absorb_lead(
        db,
        tenant_id=tenant_id,
        actor="pagina:lead",
        data=ClientCreate(name="Voltou", phone="11999998888"),
    )
    assert novo is False                      # absorveu, não criou card paralelo
    assert existente.stage_id == stages[0]    # reaberto na primeira coluna ativa
    assert _carimbo(db, perdido["id"]) > PASSADO


def test_editar_cliente_nao_reordena(client: TestClient, headers, db):
    """`updated_at` muda em qualquer edição; o carimbo da fila não pode mudar junto."""

    criado = client.post("/crm/clients", json={"name": "João"}, headers=headers).json()
    _envelhecer(db, criado["id"])

    resp = client.patch(
        f"/crm/clients/{criado['id']}", json={"name": "João Editado"}, headers=headers
    )
    assert resp.status_code == 200

    assert _carimbo(db, criado["id"]) == PASSADO
