"""wallet: platform_settings (taxas de split editáveis pelo Master)

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # GLOBAL (sem RLS) — linha única com as taxas. Só o Master edita.
    op.create_table(
        "platform_settings",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("split_product_pct", sa.Integer(), nullable=False, server_default="40"),
        sa.Column("split_service_pct", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("split_recurring_pct", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # Linha singleton padrão (40/30/20).
    op.execute(
        "INSERT INTO platform_settings (id, split_product_pct, split_service_pct, "
        "split_recurring_pct) VALUES ('platform', 40, 30, 20)"
    )


def downgrade() -> None:
    op.drop_table("platform_settings")
