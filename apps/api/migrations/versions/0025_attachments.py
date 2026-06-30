"""attachments: upload de arquivos (boleto/contrato) + RLS

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("owner_type", sa.String(24), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("label", sa.String(24), nullable=False, server_default="outro"),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_attachments_tenant_id", "attachments", ["tenant_id"])
    op.create_index("ix_attachments_owner", "attachments", ["owner_type", "owner_id"])
    op.execute("ALTER TABLE attachments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE attachments FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON attachments
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )


def downgrade() -> None:
    op.drop_table("attachments")
