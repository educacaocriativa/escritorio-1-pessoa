"""Onda 3 — o contrato do payout: modelo, registrador e fiação.

Espelha `test_bank_origin.py` (Story 8.9): **o contrato vem antes do comportamento.**
O comportamento do saque vive em `test_wallet_payout.py`.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import main as app_main
from app.modules.bank import payout as bank_payout
from app.modules.bank.models import SOURCE_PAYOUT, STATUS_MATCHED, BankTransaction
from app.modules.wallet import service as wallet_service
from app.modules.wallet.models import Payout


def test_payout_exige_bank_transaction_id(db: Session):
    """**A invariante da onda em forma de DDL: não existe `Payout` sem perna bancária.**

    É P4 = 0 escrito de forma auditável. Um `Payout` órfão significaria um saque que o razão
    bancário não conhece — exatamente o estado que esta onda existe para tornar impossível.
    """
    p = Payout(
        id="pay-1",
        tenant_id="t1",
        amount_cents=500_00,
        paid_on=date(2026, 8, 9),
        bank_account_id="acc-1",
        bank_transaction_id=None,  # ← o que precisa ser recusado
        actor="u1",
    )
    db.add(p)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_payout_persiste_completo(db: Session):
    p = Payout(
        id="pay-2",
        tenant_id="t1",
        amount_cents=500_00,
        paid_on=date(2026, 8, 9),
        bank_account_id="acc-1",
        bank_transaction_id="btx-1",
        actor="u1",
    )
    db.add(p)
    db.flush()
    assert db.get(Payout, "pay-2").amount_cents == 500_00


# ── O contrato do ponto de contato entre os planos (Onda 3) ───────────────────────────────────


def test_registrador_comeca_nao_registrado(monkeypatch):
    monkeypatch.setattr(wallet_service, "_payout_registrar", None)
    assert wallet_service.payout_registrar_registrado() is False


def test_register_payout_registrar_liga_o_registrador(monkeypatch):
    monkeypatch.setattr(wallet_service, "_payout_registrar", None)

    def _fake(db, **kwargs):
        return wallet_service.DestinoDoPayout(
            bank_account_id="acc-1", bank_transaction_id="btx-1"
        )

    wallet_service.register_payout_registrar(_fake)
    assert wallet_service.payout_registrar_registrado() is True


def test_destino_do_payout_carrega_recusa_sem_ids():
    """A forma "não deu, e o motivo é um FATO do banco" — não uma frase de tela."""
    d = wallet_service.DestinoDoPayout(recusa_detalhe="A data precisa ser posterior a 2026-07-01.")
    assert d.bank_account_id is None
    assert d.recusa_detalhe.startswith("A data")


# ── A implementação: `bank/payout.py` ─────────────────────────────────────────────────────────

REGISTER_PAYOUT = {
    "legal_name": "Payout ME",
    "document": "11444777000161",
    "slug": "payoutme",
    "email": "payout@example.com",
    "name": "Bruna",
    "password": "uma-senha-bem-grande",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER_PAYOUT).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _conta(client, headers, *, opening="2026-07-01", **over) -> dict:
    """Cria uma conta. ⚠️ **A PRIMEIRA conta do tenant nasce principal** (`service.py:937`,
    `is_primary=primary_account(db) is None`) — por isso não há parâmetro `principal=`: para
    obter um tenant *com* contas e *sem* principal é preciso ARQUIVAR a principal (AC7)."""
    payload = {
        "name": "Itaú PJ",
        "kind": "checking",
        "opening_balance_cents": 0,
        "opening_balance_is_known": True,
        "opening_date": opening,
    }
    payload.update(over)
    resp = client.post("/bank/accounts", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _tenant_id(client, headers) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]


def test_sem_conta_nenhuma_devolve_none(client: TestClient, headers, db: Session):
    """**`None` = "não há para onde mandar"**, e é valor de retorno, não exceção."""
    assert (
        bank_payout.registra_payout(
            db,
            tenant_id=_tenant_id(client, headers),
            actor="u1",
            payout_id="pay-0",
            amount_cents=500_00,
            posted_at=date(2026, 8, 9),
        )
        is None
    )


def test_principal_arquivada_sem_sucessora_devolve_none(client: TestClient, headers, db: Session):
    """O caso do **AC7**, e o único em que o tenant TEM contas e não tem principal.

    A primeira conta nasce principal; arquivá-la **não elege sucessora em silêncio** — *"escolher a
    conta de destino do dinheiro do usuário sem ele pedir é o tipo de 'ajuda' que só se descobre
    quando o dinheiro já foi para o lugar errado"*. A segunda conta existe e continua não sendo
    principal, então o saque não tem destino e o dono precisa escolher.
    """
    principal = _conta(client, headers)
    _conta(client, headers, name="Nubank", institution_code="260", branch="0001", number="9-9")
    client.post(f"/bank/accounts/{principal['id']}/archive", headers=headers)

    assert (
        bank_payout.registra_payout(
            db,
            tenant_id=_tenant_id(client, headers),
            actor="u1",
            payout_id="pay-1",
            amount_cents=500_00,
            posted_at=date(2026, 8, 9),
        )
        is None
    )


def test_escreve_movimento_positivo_conciliado(client: TestClient, headers, db: Session):
    """O crédito **entra** na conta do dono: valor POSITIVO, `source='payout'`, nasce `matched`."""
    acc = _conta(client, headers)  # primeira conta do tenant ⇒ nasce principal

    destino = bank_payout.registra_payout(
        db,
        tenant_id=_tenant_id(client, headers),
        actor="u1",
        payout_id="pay-2",
        amount_cents=500_00,
        posted_at=date(2026, 8, 9),
    )

    assert destino.bank_account_id == acc["id"]
    assert destino.recusa_detalhe is None
    mov = db.get(BankTransaction, destino.bank_transaction_id)
    assert mov.amount_cents == 500_00  # POSITIVO — é entrada
    assert mov.source == SOURCE_PAYOUT
    assert mov.origin_id == "pay-2"
    assert mov.status == STATUS_MATCHED  # nasce conciliado: o e1p originou os dois lados


def test_data_anterior_a_abertura_vira_recusa_com_o_fato(client: TestClient, headers, db: Session):
    """O piso de data não explode: volta como FATO, para a Carteira moldurar.

    Sem isto, um 422 sobre `opening_date` — vocabulário do plano do banco — vazaria cru num botão
    do plano da plataforma.

    ⚠️ **A borda real é "cadastrou a conta hoje e sacou hoje"**, e não uma data futura: a criação
    já recusa `opening_date > hoje` (`_validate_opening_date`). O movimento exige
    `posted_at > opening_date` — estritamente maior —, então conta aberta HOJE não aceita movimento
    HOJE, e o dono que acabou de cadastrar a conta bate exatamente aqui.
    """
    from app.modules.settings.service import hoje_do_tenant

    hoje = hoje_do_tenant(db)
    _conta(client, headers, opening=hoje.isoformat())

    destino = bank_payout.registra_payout(
        db,
        tenant_id=_tenant_id(client, headers),
        actor="u1",
        payout_id="pay-3",
        amount_cents=500_00,
        posted_at=hoje,
    )

    assert destino.bank_account_id is None
    assert hoje.isoformat() in destino.recusa_detalhe


# ── A fiação, e o fail-closed no boot ─────────────────────────────────────────────────────────


def test_app_nao_sobe_sem_o_registrador_de_payout(monkeypatch):
    """**Um erro de fiação é condição de startup, não de request** (ratificação §C-5.2).

    A alternativa — deixar o request seguir sem registrador — é a Onda 3 **desligada em produção
    sem ninguém saber**: o payout volta ao comportamento pré-onda (marca `withdrawn` e pronto), o
    termo P4 reabre, e a divergência cresce sem explicação, contaminando exatamente a métrica que
    decide as Ondas 4 e 5.

    Espelho de `test_bank_contagem_dupla.py::test_app_nao_sobe_sem_o_probe_de_contagem_dupla`.
    """
    monkeypatch.setattr(wallet_service, "_payout_registrar", None)
    with pytest.raises(RuntimeError, match="registrador de payout"):
        app_main.verifica_fiacao_do_payout()


def test_a_verificacao_do_payout_e_chamada_no_nivel_do_modulo():
    """Teste **ESTRUTURAL**: um fail-closed que ninguém invoca é um comentário.

    Mutante a matar: apagar a chamada de `verifica_fiacao_do_payout()` do corpo de `app/main.py`.
    Nenhum teste de comportamento pegaria — a app continuaria subindo e a guarda viraria função
    morta. Mesmo par de `test_a_guarda_de_boot_e_chamada_no_nivel_do_modulo`.
    """
    fonte = pathlib.Path(app_main.__file__).read_text(encoding="utf-8")
    tree = ast.parse(fonte)
    chamadas = {
        node.value.func.id
        for node in tree.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
    }
    assert "verifica_fiacao_do_payout" in chamadas
    assert "liga_o_registrador_de_payout" in chamadas
