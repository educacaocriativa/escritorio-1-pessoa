"""google_calendar: google_credentials (token OAuth por tenant) + RLS + agenda.google_event_id

Revision ID: 0040
Revises: 0031
Create Date: 2026-07-10

Nota de coordenação (Story 4.1): número 0040 RESERVADO para esta story entre as stories do
backlog rodando em paralelo. `down_revision="0031"` é o head no momento do desenvolvimento; se
ao mergear o head real for outro, religar o down_revision para o novo head (mesmo religamento
já feito no commit 16648b3 para a 0031).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "google_credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("google_account_email", sa.String(255), nullable=False, server_default=""),
        sa.Column("access_token", sa.Text(), nullable=False, server_default=""),
        sa.Column("refresh_token", sa.Text(), nullable=False, server_default=""),
        sa.Column("token_expiry", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "scope",
            sa.String(255),
            nullable=False,
            server_default="https://www.googleapis.com/auth/calendar.events",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_google_credentials_tenant_id", "google_credentials", ["tenant_id"])
    op.execute("ALTER TABLE google_credentials ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE google_credentials FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON google_credentials
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )
    op.add_column(
        "agenda_events", sa.Column("google_event_id", sa.String(128), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agenda_events", "google_event_id")
    op.drop_table("google_credentials")
