"""tenant_profiles: coluna timezone (fuso por tenant)

Revision ID: 0044
Revises: 0031
Create Date: 2026-07-10

Nota de coordenação: número 0044 reservado com exclusividade para a Story 4.5 entre as stories
do Epic 4 rodando em paralelo (mesmo esquema da Story 4.1 com 0040). Se, no merge, `down_revision`
não for mais o head real (outras migrations entraram), religar o encadeamento para o novo head —
mesmo ajuste já feito uma vez neste repo (commit "fix: corrige down_revision da migration 0031").
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenant_profiles",
        sa.Column(
            "timezone",
            sa.String(64),
            nullable=False,
            server_default="America/Sao_Paulo",
        ),
    )


def downgrade() -> None:
    op.drop_column("tenant_profiles", "timezone")
