"""Listagem de Contas a Pagar: paginação honesta e filtros (spec 2026-08-18).

O teste `test_teto_de_200_nao_engole_o_futuro` REPROVA o código anterior a esta spec, e é
deliberado: `list_payables` tinha `limit=200` fixo e o router não expunha `limit`/`offset`, então
a partir da 201ª conta as linhas seguintes eram inalcançáveis pela rota, sem aviso nenhum. Como a
ordenação é por vencimento crescente, o que sumia era o FUTURO — contas ainda por pagar.
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Lista Co",
    "document": "10101010000258",  # CNPJ com dígito verificador válido (validate_document)
    "slug": "listaco",
    "email": "lista@example.com",
    "name": "Lista",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _cria(client: TestClient, headers, **campos) -> dict:
    """Cria uma conta a pagar e devolve o corpo criado."""
    corpo = {
        "description": "Conta",
        "category": "Ferramentas",
        "supplier": "Fornecedor",
        "amount_cents": 10_000,
        "due_date": date(2027, 1, 10).isoformat(),
    }
    corpo.update(campos)
    resp = client.post("/payables/bills", json=corpo, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _cria_muitas(client: TestClient, headers, total: int) -> None:
    """Cria `total` contas usando recorrência mensal.

    `MAX_OCCURRENCES` (app/core/recurrence.py) e o schema limitam `recurrence_count` a 60, então
    250 contas saem em 5 POSTs de 50 em vez de 250 chamadas HTTP.
    """
    assert total % 50 == 0, "use múltiplos de 50"
    for lote in range(total // 50):
        _cria(
            client,
            headers,
            description=f"Serie {lote}",
            due_date=date(2027 + lote, 1, 10).isoformat(),
            recurrence="monthly",
            recurrence_count=50,
        )


def test_teto_de_200_nao_engole_o_futuro(client: TestClient, headers):
    _cria_muitas(client, headers, 250)

    primeira = client.get("/payables/bills?limit=50&offset=0", headers=headers)
    assert primeira.status_code == 200, primeira.text
    corpo = primeira.json()
    assert len(corpo["items"]) == 50
    assert corpo["total"] == 250, "o total tem de ser o real, não o tamanho da página"

    # A 201ª conta em diante era inalcançável pela rota antes desta spec.
    depois_do_teto = client.get("/payables/bills?limit=50&offset=200", headers=headers)
    assert depois_do_teto.status_code == 200, depois_do_teto.text
    assert len(depois_do_teto.json()["items"]) == 50
    assert depois_do_teto.json()["total"] == 250


def test_pagina_nao_repete_nem_pula_conta(client: TestClient, headers):
    _cria_muitas(client, headers, 100)
    vistos: list[str] = []
    for offset in (0, 50):
        pagina = client.get(f"/payables/bills?limit=50&offset={offset}", headers=headers).json()
        vistos.extend(item["id"] for item in pagina["items"])
    assert len(vistos) == 100
    assert len(set(vistos)) == 100, "offset repetiu conta entre páginas"
