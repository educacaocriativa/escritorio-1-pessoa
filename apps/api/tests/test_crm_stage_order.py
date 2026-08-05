"""Ordem de entrada na etapa: a fila FIFO de cada coluna do Kanban.

Spec: docs/superpowers/specs/2026-08-05-crm-ordem-de-entrada-na-etapa-design.md
"""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

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
