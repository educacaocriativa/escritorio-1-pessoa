"""Receber e pagar gravam fato — uma vez por dinheiro que entrou, sem o valor no título.

Os quatro caminhos que marcam uma cobrança como paga NÃO são equivalentes:

| caminho | o que é | emite? |
|---|---|---|
| `mark_paid` | webhook do gateway confirmou | sim |
| `settle_off_rail` | o dono registrou que caiu na conta dele | só se virar `paid`; `scheduled` é dinheiro que ainda não entrou |
| `promote_scheduled` | o worker promoveu a agendada no dia | sim — é aqui que ela vira real |
| `update_payment` | correção de data/conta de uma baixa já feita | não — corrigir não é receber de novo |

Emitir nos quatro produziria fato duplicado e, no caso da agendada, um briefing que anuncia
dinheiro que não chegou.
"""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.facts import FIN_CONTA_PAGA, FIN_PAGAMENTO_RECEBIDO, Fact

REGISTER = {
    "legal_name": "Estúdio Ana", "document": "11222333000181", "slug": "estudioana",
    "email": "ana@example.com", "name": "Ana", "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def contato(client: TestClient, headers) -> str:
    return client.post(
        "/crm/clients", json={"name": "Flavio Kato"}, headers=headers
    ).json()["id"]


def _cobranca(client: TestClient, headers, contato: str, *, dias: int = 14) -> dict:
    return client.post(
        "/receivables/charges",
        json={
            "client_id": contato, "description": "Consultoria", "kind": "service",
            "method": "pix", "amount_cents": 320000,
            "due_date": str(date.today() + timedelta(days=dias)),
        },
        headers=headers,
    ).json()


def test_baixa_pelo_gateway_grava_fato_sem_valor_no_titulo(
    client: TestClient, headers, contato, db
):
    cobranca = _cobranca(client, headers, contato)
    client.post(f"/receivables/charges/{cobranca['id']}/pay", headers=headers)

    fato = db.query(Fact).filter(Fact.kind == FIN_PAGAMENTO_RECEBIDO).one()
    assert fato.module == "financeiro"
    assert fato.subject_type == "charge"
    assert fato.subject_id == cobranca["id"]
    assert fato.client_id == contato
    # Invariante 2: o valor é lido de `charges` na composição do briefing, nunca congelado aqui.
    assert "R$" not in fato.title
    assert "Flavio Kato" in fato.title


def test_baixa_nao_duplica_o_fato_em_reenvio_de_webhook(
    client: TestClient, headers, contato, db
):
    """Webhook é at-least-once. O `return charge` idempotente tem que valer para o fato também."""
    cobranca = _cobranca(client, headers, contato)
    client.post(f"/receivables/charges/{cobranca['id']}/pay", headers=headers)
    client.post(f"/receivables/charges/{cobranca['id']}/pay", headers=headers)

    assert db.query(Fact).filter(Fact.kind == FIN_PAGAMENTO_RECEBIDO).count() == 1


def test_conta_paga_grava_fato(client: TestClient, headers, db):
    conta = client.post(
        "/payables/bills",
        json={
            "description": "Aluguel da sala", "amount_cents": 89000,
            "due_date": str(date.today()), "category": "estrutura",
        },
        headers=headers,
    ).json()
    conta_bancaria = client.post(
        "/bank/accounts",
        json={
            "name": "Itaú PJ", "kind": "checking", "institution": "Itaú Unibanco",
            "institution_code": "341", "branch": "1234", "number": "56789-0",
            "holder_document": "11.444.777/0001-61", "pix_key": "banco@example.com",
            "opening_balance_cents": 150000,
            "opening_date": str(date.today() - timedelta(days=90)),
        },
        headers=headers,
    ).json()["id"]

    client.post(
        f"/payables/bills/{conta['id']}/pay",
        json={"bank_account_id": conta_bancaria}, headers=headers,
    )

    fato = db.query(Fact).filter(Fact.kind == FIN_CONTA_PAGA).one()
    assert fato.module == "financeiro"
    assert fato.subject_type == "payable"
    assert fato.client_id is None  # conta a pagar não tem contato
    assert "R$" not in fato.title
    assert "Aluguel da sala" in fato.title
