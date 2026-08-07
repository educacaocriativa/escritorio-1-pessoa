"""Briefings da Vima

Revision ID: 0070
Revises: 0069
Create Date: 2026-08-06

Sem backfill — não há briefing anterior a esta migration, então a armadilha da RLS (o
INSERT ... SELECT que grava zero linhas em silêncio, ver 0046/0066/0067/0068/0069) não se
aplica aqui. Só DDL.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0070"
down_revision: str | None = "0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "briefings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("reference_date", sa.Date(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("por_ia", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("vazio", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "user_id", "reference_date", name="uq_briefing_dia"),
    )
    op.create_index("ix_briefings_user_id", "briefings", ["user_id"])

    op.execute("ALTER TABLE briefings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE briefings FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON briefings
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )


def downgrade() -> None:
    op.drop_table("briefings")
