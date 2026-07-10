"""platform_audit_entries: log de plataforma (fora do tenant) p/ exclusão de conta (LGPD)

Tabela GLOBAL, deliberadamente SEM tenant_id / SEM RLS: registra operações destrutivas do
Master (ex.: exclusão de conta) e SOBREVIVE à purga do tenant. Guarda snapshots (email do ator,
slug do tenant) porque o tenant-alvo é apagado logo em seguida.

Revision ID: 0031
Revises: 0030
Create Date: 2026-07-10
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_audit_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_user_id", sa.String(36), nullable=False),
        sa.Column("actor_email", sa.String(255), nullable=False),
        sa.Column("target_tenant_id", sa.String(36), nullable=False),
        sa.Column("target_tenant_slug", sa.String(63), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # SEM RLS por design: tabela de plataforma, não de tenant. É o oposto das tabelas de negócio
    # (que herdam TenantMixin e são purgadas na exclusão) — este log tem de sobreviver à purga.
    op.create_index(
        "ix_platform_audit_entries_target_tenant_id",
        "platform_audit_entries",
        ["target_tenant_id"],
    )


def downgrade() -> None:
    op.drop_table("platform_audit_entries")
