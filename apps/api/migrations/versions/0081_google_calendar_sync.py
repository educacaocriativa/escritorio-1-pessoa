"""google_calendar sync: google_credentials.sync_token + índice único de google_event_id

Revision ID: 0081
Revises: 0080
Create Date: 2026-08-26

Duas peças, as duas DDL puro, sem UPDATE nenhum — a armadilha do backfill sob FORCE RLS
(0046/0066/0067/0068/0069/0073) não se aplica aqui:

1. `google_credentials.sync_token` — o cursor de sync incremental do Google (nextSyncToken),
   um por tenant, na mesma linha que já guarda os tokens OAuth. NULL = nunca sincronizado.
2. Índice único parcial em `agenda_events (tenant_id, google_event_id)` — hoje não existe
   nenhum. Enquanto `google_event_id` só era escrito pelo e1p (push), a unicidade vinha da
   lógica de criação; agora que o sync incremental (pull) pode reprocessar uma página em caso
   de retry, uma segunda escrita do mesmo `google_event_id` tem que ser REJEITADA em vez de
   duplicar o evento. `tenant_id` na FRENTE do índice porque índice único é global e não
   respeita RLS (lição da Story 8.2, CLAUDE.md §Epic 8).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0081"
down_revision: str | None = "0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("google_credentials", sa.Column("sync_token", sa.Text(), nullable=True))
    op.create_index(
        "ix_agenda_events_tenant_google_event_id",
        "agenda_events",
        ["tenant_id", "google_event_id"],
        unique=True,
        postgresql_where=sa.text("google_event_id IS NOT NULL"),
        sqlite_where=sa.text("google_event_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_agenda_events_tenant_google_event_id", table_name="agenda_events")
    op.drop_column("google_credentials", "sync_token")
