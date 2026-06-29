"""agenda: agenda_events + RLS + índices

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enable_rls(table: str) -> None:
    # Mesma política de isolamento da 0001 (migrations são snapshots auto-contidos).
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
        "agenda_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="scheduled"),
        sa.Column("priority", sa.String(12), nullable=False, server_default="normal"),
        sa.Column("source", sa.String(24), nullable=False, server_default="manual"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("all_day", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("external_ref", sa.String(64), nullable=True),
        sa.Column("created_by_ai", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agenda_events_tenant_id", "agenda_events", ["tenant_id"])
    # Índice para a varredura de conflitos / listagem por janela de tempo.
    op.create_index(
        "ix_agenda_events_window", "agenda_events", ["tenant_id", "starts_at", "ends_at"]
    )
    _enable_rls("agenda_events")


def downgrade() -> None:
    op.drop_table("agenda_events")
