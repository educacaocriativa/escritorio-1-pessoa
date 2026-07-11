"""Story 5.2 — backfill de lançamentos legados (AC2: "lançamentos legados continuam válidos").

Simula o estado PRÉ-migration 0046 (linhas com competence_date/paid_at nulos) e roda o MESMO
backfill em SQL da migration, confirmando que:
- competence_date recebe o vencimento (payables e charges);
- paid_at de cobranças já pagas recebe a aproximação documentada (updated_at ~= momento da baixa).

A migration em si (contra Postgres real) é validada manualmente/e2e antes do merge (ver a nota de
Testing da story). Aqui garantimos a CORREÇÃO da lógica de backfill de forma portável (SQLite).
"""
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.payables.models import Payable
from app.modules.receivables.models import Charge

# Backfill textual IDÊNTICO ao de migrations/versions/0046_ledger_classification.py (AC2).
_BACKFILL = [
    "UPDATE payables SET competence_date = due_date WHERE competence_date IS NULL",
    "UPDATE charges SET competence_date = due_date WHERE competence_date IS NULL",
    "UPDATE charges SET paid_at = updated_at WHERE status = 'paid' AND paid_at IS NULL",
]


def test_backfill_fills_competence_and_paid_at(db: Session) -> None:
    # Estado LEGADO: cobrança já paga + conta a pagar, ambas SEM os campos da Story 5.2.
    paid_charge = Charge(
        tenant_id="t1", kind="service", method="pix", amount_cents=10000,
        due_date=date(2026, 8, 10), status="paid",
    )
    open_charge = Charge(
        tenant_id="t1", kind="service", method="pix", amount_cents=5000,
        due_date=date(2026, 9, 1), status="open",
    )
    payable = Payable(tenant_id="t1", amount_cents=7000, due_date=date(2026, 8, 5))
    db.add_all([paid_charge, open_charge, payable])
    db.commit()
    # Zera os campos novos para reproduzir exatamente uma linha pré-migration.
    db.execute(text("UPDATE charges SET competence_date = NULL, paid_at = NULL"))
    db.execute(text("UPDATE payables SET competence_date = NULL"))
    db.commit()

    for stmt in _BACKFILL:
        db.execute(text(stmt))
    db.commit()

    db.refresh(paid_charge)
    db.refresh(open_charge)
    db.refresh(payable)

    # competência = vencimento (regra do fallback aplicada retroativamente).
    assert paid_charge.competence_date == date(2026, 8, 10)
    assert open_charge.competence_date == date(2026, 9, 1)
    assert payable.competence_date == date(2026, 8, 5)
    # cobrança PAGA legada recebe paid_at (aproximação via updated_at); a EM ABERTO permanece None.
    assert paid_charge.paid_at is not None
    assert open_charge.paid_at is None
