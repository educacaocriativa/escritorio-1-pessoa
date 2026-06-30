"""settings: tenant_profiles (perfil + brand kit) + RLS

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("document", sa.String(18), nullable=False, server_default=""),
        sa.Column("email", sa.String(255), nullable=False, server_default=""),
        sa.Column("phone", sa.String(32), nullable=False, server_default=""),
        sa.Column("address", sa.String(500), nullable=False, server_default=""),
        sa.Column("website", sa.String(255), nullable=False, server_default=""),
        sa.Column("about", sa.Text(), nullable=False, server_default=""),
        sa.Column("logo_url", sa.String(1024), nullable=False, server_default=""),
        sa.Column("primary_color", sa.String(9), nullable=False, server_default="#5D44F8"),
        sa.Column("secondary_color", sa.String(9), nullable=False, server_default="#3DD68C"),
        sa.Column("accent_color", sa.String(9), nullable=False, server_default="#3DD68C"),
        sa.Column("text_color", sa.String(9), nullable=False, server_default="#1F2937"),
        sa.Column("bg_color", sa.String(9), nullable=False, server_default="#FFFFFF"),
        sa.Column("font", sa.String(40), nullable=False, server_default="Inter"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_tenant_profiles_tenant_id", "tenant_profiles", ["tenant_id"])
    op.execute("ALTER TABLE tenant_profiles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_profiles FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON tenant_profiles
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )


def downgrade() -> None:
    op.drop_table("tenant_profiles")
