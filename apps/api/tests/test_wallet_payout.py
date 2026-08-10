"""Onda 3 — o comportamento do saque. O contrato vive em `test_payout_registrar.py`."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.wallet.models import STATUS_WITHDRAWN, Payout, Transaction

REGISTER = {
    "legal_name": "Saque ME",
    "document": "11444777000161",
    "slug": "saqueme",
    "email": "saque@example.com",
    "name": "Bruna",
    "password": "uma-senha-bem-grande",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _conta_principal(client, headers, opening="2026-01-01") -> dict:
    """A PRIMEIRA conta do tenant nasce principal (`bank.service.create_account`)."""
    resp = client.post(
        "/bank/accounts",
        json={
            "name": "Itaú PJ",
            "kind": "checking",
            "opening_balance_cents": 0,
            "opening_balance_is_known": True,
            "opening_date": opening,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _venda(client, headers, gross=1_000_00) -> dict:
    resp = client.post(
        "/wallet/transactions",
        json={"kind": "service", "method": "pix", "gross_cents": gross, "description": "Consulta"},
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def test_saque_credita_a_conta_e_liga_as_vendas(client: TestClient, headers, db: Session):
    """O caminho feliz: um `Payout`, um movimento, e cada venda sabendo a qual saque pertence."""
    acc = _conta_principal(client, headers)
    _venda(client, headers)

    resp = client.post("/wallet/payout", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["transactions"] == 1
    assert body["payout_id"]

    payout = db.get(Payout, body["payout_id"])
    assert payout.amount_cents == body["amount_cents"]
    assert payout.bank_account_id == acc["id"]
    assert payout.bank_transaction_id  # NOT NULL, e é a invariante da onda

    txs = list(db.scalars(select(Transaction)).all())
    assert all(t.status == STATUS_WITHDRAWN and t.payout_id == payout.id for t in txs)


def test_o_credito_bancario_tem_o_valor_LIQUIDO_e_nao_o_bruto(client: TestClient, headers, db):
    """**O que cai na conta é o líquido** — o split da plataforma nunca chega ao banco do dono.

    Serviço = 30% de taxa, então R$ 1.000 brutos viram R$ 700 sacados. Se o movimento bancário
    trouxesse o bruto, a conferência acusaria uma divergência de R$ 300 **causada pelo próprio
    e1p** — e a métrica que decide as Ondas 4 e 5 mediria um erro nosso.
    """
    _conta_principal(client, headers)
    _venda(client, headers, gross=1_000_00)

    body = client.post("/wallet/payout", headers=headers).json()
    assert body["amount_cents"] == 700_00

    from app.modules.bank.models import BankTransaction

    payout = db.get(Payout, body["payout_id"])
    assert db.get(BankTransaction, payout.bank_transaction_id).amount_cents == 700_00


def test_sem_conta_principal_recusa_e_nada_muda(client: TestClient, headers, db: Session):
    """**A decisão central da onda.** Recusar é legítimo aqui porque quem ORIGINA o payout é o e1p
    — ele ainda não aconteceu. O resgate bruto da 2b-ii não podia ser recusado porque já tinha
    acontecido no banco.

    E o rollback tem de ser total: uma venda marcada `withdrawn` sem saque registrado seria dinheiro
    desaparecido da Carteira sem contrapartida em lugar nenhum.
    """
    _venda(client, headers)  # sem conta bancária nenhuma

    resp = client.post("/wallet/payout", headers=headers)
    assert resp.status_code == 409
    assert "conta" in resp.json()["detail"].lower()

    assert db.scalar(select(Transaction)).status != STATUS_WITHDRAWN
    assert db.scalars(select(Payout)).first() is None


def test_sem_saldo_recusa(client: TestClient, headers):
    _conta_principal(client, headers)
    resp = client.post("/wallet/payout", headers=headers)
    assert resp.status_code == 409
    assert "saldo" in resp.json()["detail"].lower()


def test_conta_aberta_hoje_recusa_com_a_data_dentro(client: TestClient, headers, db: Session):
    """O piso de data vira 409 com o fato dentro — não um 422 cru sobre `opening_date`.

    Cenário real: o dono cadastra a conta e tenta sacar no mesmo dia. O movimento exige
    `posted_at > opening_date`, estritamente.
    """
    from app.modules.settings.service import hoje_do_tenant

    hoje = hoje_do_tenant(db)
    _conta_principal(client, headers, opening=hoje.isoformat())
    _venda(client, headers)

    resp = client.post("/wallet/payout", headers=headers)
    assert resp.status_code == 409
    assert hoje.isoformat() in resp.json()["detail"]
    assert db.scalars(select(Payout)).first() is None
    assert db.scalar(select(Transaction)).status != STATUS_WITHDRAWN


def test_audit_aponta_para_o_payout_e_nao_para_o_valor(client: TestClient, headers, db: Session):
    """`target=str(total)` era o VALOR — trilha apontando para lugar nenhum (a família MNT-001)."""
    from app.core.audit import AuditEntry

    _conta_principal(client, headers)
    _venda(client, headers)
    payout_id = client.post("/wallet/payout", headers=headers).json()["payout_id"]

    log = db.scalars(select(AuditEntry).where(AuditEntry.action == "wallet.payout")).first()
    assert log.target == payout_id


def test_historico_traz_todos_os_saques_com_perna_bancaria(client: TestClient, headers):
    _conta_principal(client, headers)
    _venda(client, headers, gross=1_000_00)
    primeiro = client.post("/wallet/payout", headers=headers).json()["payout_id"]
    _venda(client, headers, gross=2_000_00)
    segundo = client.post("/wallet/payout", headers=headers).json()["payout_id"]

    resp = client.get("/wallet/payouts", headers=headers)
    assert resp.status_code == 200, resp.text
    assert {p["id"] for p in resp.json()} == {primeiro, segundo}
    # Todo saque tem perna bancária — a invariante da onda, vista pela porta de saída.
    assert all(p["bank_transaction_id"] for p in resp.json())
    assert [p["amount_cents"] for p in sorted(resp.json(), key=lambda p: p["amount_cents"])] == [
        700_00,
        1_400_00,
    ]


def test_historico_tem_ordem_ESTAVEL_entre_chamadas_identicas(client: TestClient, headers):
    """⚠️ **Não afirma "mais novo primeiro" — afirma que a ordem não muda sozinha.**

    Os dois saques caem no mesmo segundo, e `created_at` (`server_default=now()`) tem resolução de
    segundo no SQLite: dentro do mesmo instante **não existe "mais novo"**, e um teste que
    afirmasse a ordem cronológica aqui estaria testando o acaso — passaria ou falharia conforme o
    plano de execução, e o próximo a vê-lo vermelho "consertaria" invertendo a asserção.

    O que o produto precisa garantir é que a lista **não se reordena entre dois cliques**. A ordem
    cronológica de verdade é exercitada no Postgres (`test_payout_rls.py`), onde `now()` tem
    resolução de microssegundo.
    """
    _conta_principal(client, headers)
    _venda(client, headers, gross=1_000_00)
    client.post("/wallet/payout", headers=headers)
    _venda(client, headers, gross=2_000_00)
    client.post("/wallet/payout", headers=headers)

    uma = [p["id"] for p in client.get("/wallet/payouts", headers=headers).json()]
    outra = [p["id"] for p in client.get("/wallet/payouts", headers=headers).json()]
    assert uma == outra
    assert len(uma) == 2
