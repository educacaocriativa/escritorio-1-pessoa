"""tenant_profiles.whatsapp_provider + public_whatsapp_instances (Onda 2 — onboarding por QR)

Revision ID: 0061
Revises: 0060
Create Date: 2026-07-30

- `tenant_profiles.whatsapp_provider`: "meta" | "evolution" | None. None = nenhum transporte
  ativo (estado de hoje — nenhum tenant existente muda de comportamento).
- `public_whatsapp_instances` (GLOBAL, sem RLS): resolve `instance_name -> tenant_id` +
  `webhook_secret` ANTES de qualquer autenticação (mesmo padrão de `public_whatsapp_accounts`,
  chave natural distinta: nome de instância, não phone_number_id da Meta).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0061"
down_revision: str | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenant_profiles", sa.Column("whatsapp_provider", sa.String(16), nullable=True)
    )
    op.create_table(
        "public_whatsapp_instances",
        sa.Column("instance_name", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("webhook_secret", sa.Text(), nullable=False),
        sa.Column("last_status", sa.String(16), nullable=False, server_default="connecting"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_public_whatsapp_instances_tenant_id", "public_whatsapp_instances", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_public_whatsapp_instances_tenant_id", table_name="public_whatsapp_instances"
    )
    op.drop_table("public_whatsapp_instances")
    op.drop_column("tenant_profiles", "whatsapp_provider")
