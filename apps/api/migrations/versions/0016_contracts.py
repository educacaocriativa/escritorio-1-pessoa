"""contracts: templates, contracts (RLS) + published_contracts (global, sem RLS)

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
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
        "contract_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("clauses", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_contract_templates_tenant_id", "contract_templates", ["tenant_id"])
    _enable_rls("contract_templates")

    op.create_table(
        "contracts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("client_id", sa.String(36), nullable=True),
        sa.Column("quote_id", sa.String(36), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("clauses", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
        sa.Column("public_slug", sa.String(64), nullable=True),
        sa.Column("signer_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("signer_document", sa.String(32), nullable=False, server_default=""),
        sa.Column("signer_ip", sa.String(64), nullable=False, server_default=""),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_contracts_tenant_id", "contracts", ["tenant_id"])
    op.create_index("ix_contracts_client_id", "contracts", ["client_id"])
    op.create_unique_constraint("uq_contracts_public_slug", "contracts", ["public_slug"])
    _enable_rls("contracts")

    op.create_table(
        "published_contracts",
        sa.Column("slug", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("contract_id", sa.String(36), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("company_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_published_contracts_contract_id", "published_contracts", ["contract_id"])


def downgrade() -> None:
    op.drop_table("published_contracts")
    op.drop_table("contracts")
    op.drop_table("contract_templates")
