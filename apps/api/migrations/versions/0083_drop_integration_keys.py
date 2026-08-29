"""remove integrações: chaves de captura de lead de site externo (feature sem uso real)

Revision ID: 0083
Revises: 0082
Create Date: 2026-08-28

O único caso de uso conhecido (Doro) nunca usou este mecanismo — o site externo embute a
página pública do construtor de Sites via iframe (`/p/:slug`, PR #43), que cria o lead com
`source="landing"` sem chave nenhuma. As duas chaves que chegaram a existir (uma de teste, uma
rotulada "site Doro") já estavam revogadas. Módulo `app/modules/integrations/` removido junto.

`tenant_profiles.default_entry_funnel_id` (migration 0051) NÃO é tocada aqui: é o funil de
entrada padrão para QUALQUER lead novo (source=landing/api/manual/...), não exclusiva desta
feature — pages/service.py e crm/service.py continuam usando.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0083"
down_revision: str | None = "0082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("public_integration_keys")
    op.drop_index("ix_integration_keys_tenant_id", table_name="integration_keys")
    op.drop_table("integration_keys")


def downgrade() -> None:
    import sqlalchemy as sa

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
