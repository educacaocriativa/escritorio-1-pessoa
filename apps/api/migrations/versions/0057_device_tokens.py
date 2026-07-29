"""device_tokens: credencial de escopo único para o Atalho do iOS

Revision ID: 0057
Revises: 0056
Create Date: 2026-07-28

Tabela GLOBAL, deliberadamente SEM RLS: o tenant é resolvido A PARTIR do token (o cliente não
tem sessão), então nenhuma `tenant_session` existe no momento do lookup — mesma situação de
`users` e `public_whatsapp_accounts`. Guarda só hash de credencial e metadado.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "device_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False, server_default="receipt_upload"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_device_tokens_tenant_id", "device_tokens", ["tenant_id"])
    op.create_index("ix_device_tokens_user_id", "device_tokens", ["user_id"])
    # Índice do lookup por hash (caminho quente de toda requisição do atalho).
    op.create_index("ix_device_tokens_token_hash", "device_tokens", ["token_hash"])


def downgrade() -> None:
    op.drop_table("device_tokens")
