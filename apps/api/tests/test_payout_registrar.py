"""Onda 3 — o contrato do payout: modelo, registrador e fiação.

Espelha `test_bank_origin.py` (Story 8.9): **o contrato vem antes do comportamento.**
O comportamento do saque vive em `test_wallet_payout.py`.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
