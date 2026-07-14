"""lead auto-enroll: funil de entrada padrão do tenant + chaves de captura de lead

Revision ID: 0051
Revises: 0050
Create Date: 2026-07-14

Duas mudanças independentes, na mesma migration por serem parte da mesma story (auto-enroll de
leads no funil de vendas):

1. `tenant_profiles.default_entry_funnel_id` (nullable, sem FK dura — mesmo padrão de
   `quote_id`/`contract_id` no projeto): o funil em que todo lead novo (source=landing/api) é
   inscrito automaticamente. Estritamente ADITIVA, sem backfill (NULL = "sem auto-enroll", o
   comportamento de hoje).
2. `integration_keys` (RLS) + `public_integration_keys` (global, sem RLS) — mesmo par
   RLS/snapshot já usado por pages/quotes/contracts, aqui para a API pública de captura de lead
   (`POST /public/leads/{key}`) resolver o tenant dono ANTES de qualquer autenticação.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenant_profiles", sa.Column("default_entry_funnel_id", sa.String(36), nullable=True)
    )

    op.create_table(
        "integration_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("key_prefix", sa.String(8), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_integration_keys_tenant_id", "integration_keys", ["tenant_id"])
    op.execute("ALTER TABLE integration_keys ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE integration_keys FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON integration_keys
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )

    op.create_table(
        "public_integration_keys",
        sa.Column("key_hash", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("public_integration_keys")
    op.drop_index("ix_integration_keys_tenant_id", table_name="integration_keys")
    op.drop_table("integration_keys")
    op.drop_column("tenant_profiles", "default_entry_funnel_id")
