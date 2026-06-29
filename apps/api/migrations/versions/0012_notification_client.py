"""notifications: client_id (histórico de mensagens por cliente)

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("client_id", sa.String(36), nullable=True))
    op.create_index("ix_notifications_client_id", "notifications", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_notifications_client_id", table_name="notifications")
    op.drop_column("notifications", "client_id")
