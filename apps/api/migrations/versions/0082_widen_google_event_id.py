"""agenda_events.google_event_id: VARCHAR(128) -> VARCHAR(1024)

Revision ID: 0082
Revises: 0081
Create Date: 2026-08-27

Incidente de produção (2026-08-27, algumas horas após o deploy da 0081): eventos importados de
calendários externos (Outlook/Exchange via interop do Google Workspace) chegam com `id` de até
181 caracteres — medido ao vivo, 3 ocorrências reais na conta conectada. `google_event_id` era
`String(128)`: o INSERT do sync (google_calendar/sync.py::pull_changes) falhava com
`StringDataRightTruncation`, e como o `pull_changes` grava o lote inteiro numa única transação,
UM evento comprido derrubava a sincronização de TODOS os outros eventos daquele tenant naquela
rodada — sintoma relatado pelo dono como "nada do celular volta pro sistema".

1024 é o máximo documentado pela Google Calendar API para o campo `id` do evento — não é um
número arredondado, é o teto real do domínio.

DDL puro (`ALTER COLUMN TYPE`, VARCHAR→VARCHAR maior): sem UPDATE, sem backfill, a armadilha do
FORCE RLS não se aplica. O índice único `ix_agenda_events_tenant_google_event_id` (migration
0081) não precisa ser recriado — VARCHAR(1024) cabe folgado no limite de ~2704 bytes por entrada
de índice btree do Postgres (tenant_id é 36 chars fixos + até 1024 do google_event_id, bem abaixo
do teto).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0082"
down_revision: str | None = "0081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "agenda_events",
        "google_event_id",
        existing_type=sa.String(128),
        type_=sa.String(1024),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "agenda_events",
        "google_event_id",
        existing_type=sa.String(1024),
        type_=sa.String(128),
        existing_nullable=True,
    )
