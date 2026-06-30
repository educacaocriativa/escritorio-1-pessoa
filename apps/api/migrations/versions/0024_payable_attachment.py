"""payables: payment_code (boleto/pix) + attachment_url (boleto anexado)

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payables", sa.Column("payment_code", sa.Text(), nullable=False, server_default="")
    )
    op.add_column(
        "payables",
        sa.Column("attachment_url", sa.String(1024), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("payables", "attachment_url")
    op.drop_column("payables", "payment_code")
