"""juridico: documentos jurídicos gerados por IA (Assistente Jurídico) + RLS

Revision ID: 0027
Revises: 0026
Create Date: 2026-06-30
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "legal_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("skill", sa.String(60), nullable=False),
        sa.Column("category", sa.String(24), nullable=False, server_default="core"),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("client_id", sa.String(36), nullable=True),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata_raw", sa.Text(), nullable=False, server_default=""),
        sa.Column("answers", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(12), nullable=False, server_default="ready"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_legal_documents_tenant_id", "legal_documents", ["tenant_id"])
    op.create_index("ix_legal_documents_client", "legal_documents", ["client_id"])
    op.execute("ALTER TABLE legal_documents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE legal_documents FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON legal_documents
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )


def downgrade() -> None:
    op.drop_table("legal_documents")
