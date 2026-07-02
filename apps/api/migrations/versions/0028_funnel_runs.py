"""funnel_runs: jornadas de automação por contato (motor do funil) + RLS

Revision ID: 0028
Revises: 0027
Create Date: 2026-06-30
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "funnel_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("funnel_id", sa.String(36), nullable=False),
        sa.Column("client_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="running"),
        sa.Column("current_node_id", sa.String(64), nullable=True),
        sa.Column("resume_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("steps", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("error", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_funnel_runs_tenant_id", "funnel_runs", ["tenant_id"])
    op.create_index("ix_funnel_runs_funnel", "funnel_runs", ["funnel_id"])
    op.create_index("ix_funnel_runs_client", "funnel_runs", ["client_id"])
    # índice p/ o agendador varrer esperas vencidas de forma barata
    op.create_index("ix_funnel_runs_due", "funnel_runs", ["status", "resume_at"])
    op.execute("ALTER TABLE funnel_runs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE funnel_runs FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON funnel_runs
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )


def downgrade() -> None:
    op.drop_table("funnel_runs")
