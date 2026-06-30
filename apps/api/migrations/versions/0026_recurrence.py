"""payables/charges: recurrence_count + recurrence_group (e recurrence em charges)

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payables", sa.Column("recurrence_count", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column("payables", sa.Column("recurrence_group", sa.String(36), nullable=True))

    op.add_column(
        "charges", sa.Column("recurrence", sa.String(8), nullable=False, server_default="none")
    )
    op.add_column(
        "charges", sa.Column("recurrence_count", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column("charges", sa.Column("recurrence_group", sa.String(36), nullable=True))


def downgrade() -> None:
    op.drop_column("charges", "recurrence_group")
    op.drop_column("charges", "recurrence_count")
    op.drop_column("charges", "recurrence")
    op.drop_column("payables", "recurrence_group")
    op.drop_column("payables", "recurrence_count")
