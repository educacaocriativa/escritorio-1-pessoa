"""carousels: handle + caption + hashtags (estilo editorial)

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("carousels", sa.Column("handle", sa.String(120), nullable=False,
                                         server_default=""))
    op.add_column("carousels", sa.Column("caption", sa.Text(), nullable=False, server_default=""))
    op.add_column("carousels", sa.Column("hashtags", sa.String(600), nullable=False,
                                         server_default=""))


def downgrade() -> None:
    op.drop_column("carousels", "hashtags")
    op.drop_column("carousels", "caption")
    op.drop_column("carousels", "handle")
