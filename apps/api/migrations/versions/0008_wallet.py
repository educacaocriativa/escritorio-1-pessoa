"""wallet: transactions (RLS) + platform_earnings (global)

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
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
        "transactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("gross_cents", sa.BigInteger(), nullable=False),
        sa.Column("platform_fee_cents", sa.BigInteger(), nullable=False),
        sa.Column("net_cents", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="available"),
        sa.Column("client_id", sa.String(36), nullable=True),
        sa.Column("external_ref", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_transactions_tenant_id", "transactions", ["tenant_id"])
    op.create_index("ix_transactions_status", "transactions", ["tenant_id", "status"])
    _enable_rls("transactions")

    # GLOBAL — sem RLS (só o Master agrega).
    op.create_table(
        "platform_earnings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("gross_cents", sa.BigInteger(), nullable=False),
        sa.Column("fee_cents", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_platform_earnings_tenant_id", "platform_earnings", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("platform_earnings")
    op.drop_table("transactions")
