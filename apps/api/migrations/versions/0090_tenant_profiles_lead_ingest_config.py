"""tenant_profiles.lead_ingest_config: produto e funil por evento da ingestão de leads

Revision ID: 0090
Revises: 0089
Create Date: 2026-09-30

`{}` = o comportamento de um tenant que nunca configurou nada. O `server_default` é o que
preenche as linhas existentes, como DDL: um `UPDATE` aqui rodaria sob FORCE RLS sem
`app.current_tenant_id`, seria filtrado a zero linhas e "passaria" em silêncio.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0090"
down_revision: str | None = "0089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenant_profiles",
        sa.Column("lead_ingest_config", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("tenant_profiles", "lead_ingest_config")
