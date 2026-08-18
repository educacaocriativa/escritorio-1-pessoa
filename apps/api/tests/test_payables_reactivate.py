"""Reativar conta cancelada (spec 2026-08-18, §6).

Reativar é rota PRÓPRIA, não `/reverse`: aquele apaga movimento bancário, e conta cancelada nunca
teve um — `cancel_payable` só aceita conta em aberto.
"""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.tz import DEFAULT_TENANT_TIMEZONE, tenant_today

REGISTER = {
    "legal_name": "Reativa Co",
    "document": "10101010000339",  # CNPJ com dígito verificador válido (validate_document)
    "slug": "reativaco",
    "email": "reativa@example.com",
    "name": "Reativa",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _cria(client: TestClient, headers, **campos) -> dict:
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


def test_cancelada_volta_para_aberta_com_vencimento_intacto(client: TestClient, headers):
    conta = _cria(client, headers, due_date="2027-01-10")
    client.post(f"/payables/bills/{conta['id']}/cancel", headers=headers)

    resp = client.post(f"/payables/bills/{conta['id']}/reactivate", headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "open"
    assert resp.json()["due_date"] == "2027-01-10", "o vencimento contratado não se reescreve"


def test_reativada_com_vencimento_passado_nasce_atrasada(client: TestClient, headers):
    """Vencimento preservado + `is_overdue` derivado = ela volta Atrasada, que é o que ela é.

    A data vem de `tenant_today`, nunca da hora em que a suíte roda.
    """
    ontem = tenant_today(DEFAULT_TENANT_TIMEZONE) - timedelta(days=1)
    conta = _cria(client, headers, due_date=ontem.isoformat())
    client.post(f"/payables/bills/{conta['id']}/cancel", headers=headers)

    resp = client.post(f"/payables/bills/{conta['id']}/reactivate", headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "open"
    assert resp.json()["is_overdue"] is True


def test_conta_aberta_nao_pode_ser_reativada(client: TestClient, headers):
    conta = _cria(client, headers)
    resp = client.post(f"/payables/bills/{conta['id']}/reactivate", headers=headers)
    assert resp.status_code == 409
    assert "cancelada" in resp.json()["detail"].lower()


def test_conta_paga_nao_pode_ser_reativada(client: TestClient, headers):
    """Conta paga tem movimento bancário atrás dela; o caminho de volta dela é `/reverse`."""
    resp_conta = client.post(
        "/bank/accounts",
        json={
            "name": "Itaú PJ",
            "kind": "checking",
            "opening_balance_cents": 500_000,
            "opening_balance_is_known": True,
            "opening_date": "2026-01-01",
        },
        headers=headers,
    )
    assert resp_conta.status_code == 201, resp_conta.text
    banco = resp_conta.json()["id"]
    hoje = tenant_today(DEFAULT_TENANT_TIMEZONE).isoformat()
    conta = _cria(client, headers, due_date=hoje)
    paga = client.post(
        f"/payables/bills/{conta['id']}/pay",
        json={"bank_account_id": banco, "paid_on": hoje},
        headers=headers,
    )
    assert paga.status_code == 200, paga.text

    resp = client.post(f"/payables/bills/{conta['id']}/reactivate", headers=headers)
    assert resp.status_code == 409


def test_conta_inexistente_devolve_404(client: TestClient, headers):
    resp = client.post("/payables/bills/nao-existe/reactivate", headers=headers)
    assert resp.status_code == 404


def test_reativacao_entra_na_auditoria(client: TestClient, headers, db):
    from sqlalchemy import select

    from app.core.audit import AuditEntry

    conta = _cria(client, headers)
    client.post(f"/payables/bills/{conta['id']}/cancel", headers=headers)
    client.post(f"/payables/bills/{conta['id']}/reactivate", headers=headers)

    acoes = list(db.scalars(select(AuditEntry.action).where(AuditEntry.target == conta["id"])))
    assert "payable.reactivate" in acoes
