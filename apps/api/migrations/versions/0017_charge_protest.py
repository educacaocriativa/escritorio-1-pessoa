"""charges: protested_at (protesto de cobrança)

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("charges", sa.Column("protested_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("charges", "protested_at")
