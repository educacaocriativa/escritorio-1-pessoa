"""agenda: location, meeting_url, guests (estilo Google Agenda)

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agenda_events", sa.Column("location", sa.String(255), nullable=False, server_default="")
    )
    op.add_column("agenda_events", sa.Column("meeting_url", sa.String(512), nullable=True))
    op.add_column(
        "agenda_events", sa.Column("guests", sa.JSON(), nullable=False, server_default="[]")
    )


def downgrade() -> None:
    op.drop_column("agenda_events", "guests")
    op.drop_column("agenda_events", "meeting_url")
    op.drop_column("agenda_events", "location")
