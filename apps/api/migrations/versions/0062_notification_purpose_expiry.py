"""notifications ganha purpose/expires_at/next_attempt_at (Onda 3 — fila com validade)

Revision ID: 0062
Revises: 0061
Create Date: 2026-07-30

- `purpose`: propósito do envio (ex.: "charge_reminder", "funnel_node") — usado para resolver a
  validade (Onda 3 §Fase B). None = compatibilidade com linhas antigas (nunca expiram sozinhas).
- `expires_at`: calculado no enfileiramento; passado disso, `process_pending` marca "expired"
  em vez de tentar entregar.
- `next_attempt_at`: retry com backoff exponencial, limitado pela validade (nunca agenda
  tentativa depois de expirar).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0062"
down_revision: str | None = "0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("purpose", sa.String(32), nullable=True))
    op.add_column(
        "notifications", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "notifications", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("notifications", "next_attempt_at")
    op.drop_column("notifications", "expires_at")
    op.drop_column("notifications", "purpose")
