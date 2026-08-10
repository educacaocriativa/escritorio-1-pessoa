"""Onda 3 — o contrato do payout: modelo, registrador e fiação.

Espelha `test_bank_origin.py` (Story 8.9): **o contrato vem antes do comportamento.**
O comportamento do saque vive em `test_wallet_payout.py`.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
