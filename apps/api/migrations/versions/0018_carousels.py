"""carousels: gerador de carrossel (Marketing) + RLS

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "carousels",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("topic", sa.String(500), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False, server_default="instagram"),
        sa.Column("slides", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
        sa.Column("template", sa.String(24), nullable=False, server_default="moderno"),
        sa.Column("primary_color", sa.String(9), nullable=False, server_default="#5D44F8"),
        sa.Column("bg_color", sa.String(9), nullable=False, server_default="#0F1020"),
        sa.Column("text_color", sa.String(9), nullable=False, server_default="#FFFFFF"),
        sa.Column("accent_color", sa.String(9), nullable=False, server_default="#3DD68C"),
        sa.Column("font", sa.String(40), nullable=False, server_default="Inter"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_carousels_tenant_id", "carousels", ["tenant_id"])
    op.execute("ALTER TABLE carousels ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE carousels FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON carousels
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )


def downgrade() -> None:
    op.drop_table("carousels")
