"""machine_tokens: credencial de máquina com escopo, por tenant (ingestão de leads)

Revision ID: 0088
Revises: 0087
Create Date: 2026-09-30

Reconstrói, com escopo e contrato novos, a capacidade que a 0083 removeu (chave de API de
"Integrações", PR #270): o caso que a própria nota de remoção previu — site headless que não
embute iframe — apareceu (site da Nexus Pública → `POST /public/ingest/leads`).

Tabela GLOBAL, deliberadamente SEM RLS, pela mesma razão de `device_tokens` (0057): o tenant é
resolvido A PARTIR do token, antes de existir `tenant_session`. Guarda só hash sha256 e
metadado. DDL puro, sem UPDATE.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0088"
down_revision: str | None = "0087"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "machine_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_machine_tokens_tenant_id", "machine_tokens", ["tenant_id"])
    # Único: é o caminho quente de toda requisição, e dois tokens com o mesmo hash seriam
    # a mesma credencial com dois donos.
    op.create_index("ix_machine_tokens_token_hash", "machine_tokens", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_table("machine_tokens")
