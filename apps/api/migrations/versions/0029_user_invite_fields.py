"""users: cadastro completo (CPF/endereço/WhatsApp) + troca de senha no 1º acesso

Revision ID: 0029
Revises: 0028
Create Date: 2026-06-30
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("document", sa.String(18), nullable=True))
    op.add_column("users", sa.Column("address", sa.String(500), nullable=True))
    op.add_column("users", sa.Column("phone", sa.String(32), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "must_reset_password", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "must_reset_password")
    op.drop_column("users", "phone")
    op.drop_column("users", "address")
    op.drop_column("users", "document")
