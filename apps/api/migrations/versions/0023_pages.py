"""pages: construtor de páginas (RLS) + published_pages (global, sem RLS)

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("model", sa.String(24), nullable=False, server_default="conteudo"),
        sa.Column("blocks", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
        sa.Column("public_slug", sa.String(64), nullable=True),
        sa.Column("primary_color", sa.String(9), nullable=False, server_default="#5D44F8"),
        sa.Column("bg_color", sa.String(9), nullable=False, server_default="#FFFFFF"),
        sa.Column("text_color", sa.String(9), nullable=False, server_default="#1F2937"),
        sa.Column("accent_color", sa.String(9), nullable=False, server_default="#3DD68C"),
        sa.Column("font", sa.String(40), nullable=False, server_default="Inter"),
        sa.Column("logo_url", sa.String(1024), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_pages_tenant_id", "pages", ["tenant_id"])
    op.create_unique_constraint("uq_pages_public_slug", "pages", ["public_slug"])
    op.execute("ALTER TABLE pages ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE pages FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON pages
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )

    op.create_table(
        "published_pages",
        sa.Column("slug", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("page_id", sa.String(36), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_published_pages_page_id", "published_pages", ["page_id"])


def downgrade() -> None:
    op.drop_table("published_pages")
    op.drop_table("pages")
