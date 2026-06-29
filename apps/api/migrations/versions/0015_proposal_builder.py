"""quotes: campos do construtor de proposta + published_proposals (global, sem RLS)

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _col(name, type_, **kw):
    op.add_column("quotes", sa.Column(name, type_, **kw))


def upgrade() -> None:
    # --- novos campos do editor em quotes ---
    txt = {"nullable": False, "server_default": ""}
    _col("client_name", sa.String(255), **txt)
    _col("client_whatsapp", sa.String(32), **txt)
    _col("payment_terms", sa.Text(), **txt)
    _col("link_password_hash", sa.String(255), nullable=True)
    _col("show_gallery", sa.Boolean(), nullable=False, server_default=sa.false())
    _col("gallery", sa.JSON(), nullable=False, server_default="[]")
    _col("show_schedule", sa.Boolean(), nullable=False, server_default=sa.false())
    _col("schedule", sa.JSON(), nullable=False, server_default="[]")
    _col("show_contract", sa.Boolean(), nullable=False, server_default=sa.false())
    _col("contract_text", sa.Text(), **txt)
    _col("logo_url", sa.String(512), **txt)
    _col("primary_color", sa.String(9), nullable=False, server_default="#5D44F8")
    _col("bg_color", sa.String(9), nullable=False, server_default="#FFFFFF")
    _col("text_color", sa.String(9), nullable=False, server_default="#1F2937")
    _col("accent_color", sa.String(9), nullable=False, server_default="#3DD68C")
    _col("public_slug", sa.String(64), nullable=True)
    op.create_unique_constraint("uq_quotes_public_slug", "quotes", ["public_slug"])

    # --- snapshot público GLOBAL (sem RLS) ---
    op.create_table(
        "published_proposals",
        sa.Column("slug", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("quote_id", sa.String(36), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_published_proposals_quote_id", "published_proposals", ["quote_id"])


def downgrade() -> None:
    op.drop_table("published_proposals")
    op.drop_constraint("uq_quotes_public_slug", "quotes", type_="unique")
    for col in (
        "public_slug", "accent_color", "text_color", "bg_color", "primary_color", "logo_url",
        "contract_text", "show_contract", "schedule", "show_schedule", "gallery", "show_gallery",
        "link_password_hash", "payment_terms", "client_whatsapp", "client_name",
    ):
        op.drop_column("quotes", col)
