"""payables: contas a pagar + RLS

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )


def upgrade() -> None:
    op.create_table(
        "payables",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(48), nullable=False, server_default="Geral"),
        sa.Column("supplier", sa.String(120), nullable=False, server_default=""),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="open"),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recurrence", sa.String(8), nullable=False, server_default="none"),
        sa.Column("agenda_event_id", sa.String(36), nullable=True),
        sa.Column("external_ref", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_payables_tenant_id", "payables", ["tenant_id"])
    op.create_index("ix_payables_status", "payables", ["tenant_id", "status"])
    _enable_rls("payables")


def downgrade() -> None:
    op.drop_table("payables")
