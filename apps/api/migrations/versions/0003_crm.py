"""crm: pipeline_stages, clients + RLS

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
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
        "pipeline_stages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_won", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_lost", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "name", name="uq_stage_tenant_name"),
    )
    op.create_index("ix_pipeline_stages_tenant_id", "pipeline_stages", ["tenant_id"])
    _enable_rls("pipeline_stages")

    op.create_table(
        "clients",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("document", sa.String(18), nullable=True),
        sa.Column("gender", sa.String(12), nullable=False, server_default="unspecified"),
        sa.Column("birthdate", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column(
            "stage_id",
            sa.String(36),
            sa.ForeignKey("pipeline_stages.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_clients_tenant_id", "clients", ["tenant_id"])
    op.create_index("ix_clients_stage_id", "clients", ["stage_id"])
    _enable_rls("clients")


def downgrade() -> None:
    op.drop_table("clients")
    op.drop_table("pipeline_stages")
