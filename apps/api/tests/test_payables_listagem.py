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


def test_status_aceita_mais_de_um_valor(client: TestClient, headers):
    aberta = _cria(client, headers, description="Aberta")
    cancelada = _cria(client, headers, description="Cancelada")
    client.post(f"/payables/bills/{cancelada['id']}/cancel", headers=headers)

    corpo = client.get("/payables/bills?status=open&status=scheduled", headers=headers).json()
    ids = [i["id"] for i in corpo["items"]]
    assert aberta["id"] in ids
    assert cancelada["id"] not in ids
    assert corpo["total"] == len(ids)


def test_from_ausente_nao_engole_atrasado_antigo(client: TestClient, headers):
    """A visão padrão da tela NÃO manda `from`. Se alguém "simplificar" pondo um piso de data, a
    conta mais urgente que existe — a vencida — some justamente da tela que serve para pagá-la."""
    antiga = _cria(client, headers, description="Vencida", due_date="2026-02-01")
    futura = _cria(client, headers, description="Futura", due_date="2027-01-10")

    corpo = client.get("/payables/bills?status=open&to=2027-06-30", headers=headers).json()
    ids = [i["id"] for i in corpo["items"]]
    assert antiga["id"] in ids, "atrasado antigo tem de aparecer sem `from`"
    assert futura["id"] in ids


def test_to_e_inclusivo_na_borda(client: TestClient, headers):
    na_borda = _cria(client, headers, description="Borda", due_date="2027-03-31")
    depois = _cria(client, headers, description="Depois", due_date="2027-04-01")

    corpo = client.get("/payables/bills?to=2027-03-31", headers=headers).json()
    ids = [i["id"] for i in corpo["items"]]
    assert na_borda["id"] in ids
    assert depois["id"] not in ids


def test_q_busca_em_descricao_e_em_fornecedor(client: TestClient, headers):
    por_descricao = _cria(client, headers, description="Assinatura Anthropic", supplier="X")
    por_fornecedor = _cria(client, headers, description="Ferramenta", supplier="Anthropic")
    outra = _cria(client, headers, description="Aluguel", supplier="Imobiliaria")

    corpo = client.get("/payables/bills?q=anthropic", headers=headers).json()
    ids = [i["id"] for i in corpo["items"]]
    assert por_descricao["id"] in ids, "busca tem de ser case-insensitive"
    assert por_fornecedor["id"] in ids
    assert outra["id"] not in ids


def test_q_escapa_curinga_do_like(client: TestClient, headers):
    """`ilike` interpreta `%` e `_`. Sem escape, digitar `%` casa com TUDO e a busca parece estar
    funcionando quando não está filtrando nada. A implementação ingênua passa em todos os outros
    testes e falha só neste."""
    com_percent = _cria(client, headers, description="100% Cacau", supplier="Doceria")
    sem_percent = _cria(client, headers, description="Anthropic", supplier="X")

    corpo = client.get("/payables/bills?q=%25", headers=headers).json()  # %25 = "%"
    ids = [i["id"] for i in corpo["items"]]
    assert com_percent["id"] in ids
    assert sem_percent["id"] not in ids
    assert corpo["total"] == 1


def test_order_desc_inverte_a_lista(client: TestClient, headers):
    _cria(client, headers, description="Primeira", due_date="2027-01-10")
    _cria(client, headers, description="Ultima", due_date="2027-09-10")

    asc = client.get("/payables/bills?order=asc", headers=headers).json()["items"]
    desc = client.get("/payables/bills?order=desc", headers=headers).json()["items"]
    assert asc[0]["description"] == "Primeira"
    assert desc[0]["description"] == "Ultima"


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?status=open",
        "?status=open&status=scheduled",
        "?to=2027-06-30",
        "?from=2027-01-01&to=2027-12-31",
        "?q=anthropic",
        "?q=anthropic&status=open",
    ],
)
def test_total_sempre_casa_com_a_lista(client: TestClient, headers, query: str):
    """O alarme contra `list_payables` e `count_payables` divergirem de predicado."""
    _cria(client, headers, description="Assinatura Anthropic", due_date="2027-01-10")
    _cria(client, headers, description="Aluguel", due_date="2027-05-10")
    _cria(client, headers, description="Curso", due_date="2028-01-10")

    sep = "&" if query else "?"
    corpo = client.get(f"/payables/bills{query}{sep}limit=500", headers=headers).json()
    assert corpo["total"] == len(corpo["items"]), f"total divergiu da lista em {query!r}"
