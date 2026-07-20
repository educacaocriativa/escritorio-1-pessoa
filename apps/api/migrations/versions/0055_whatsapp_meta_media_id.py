"""whatsapp_messages ganha meta_media_id (separado de 0054)

Revision ID: 0055
Revises: 0054
Create Date: 2026-07-19

Achado da revisão final de branch: `meta_media_id` foi adicionado a `whatsapp_messages` editando
o arquivo `0054_whatsapp_inbox.py` DEPOIS que essa migration já havia rodado (e sido "stampada"
em `alembic_version`) em pelo menos um ambiente de dev compartilhado. Editar uma migration já
aplicada é silenciosamente ignorado por `alembic upgrade head` (o hash da revisão não muda) — o
banco fica divergente do modelo até alguém rodar a DDL manualmente. O smoke test manual (Task 11)
já reproduziu esse exato sintoma: todo webhook inbound quebrava com `UndefinedColumn:
meta_media_id`. Esta migration própria garante que qualquer ambiente que já tenha `0054`
stampada (na versão original, sem `meta_media_id`) recebe a coluna faltante ao rodar
`alembic upgrade head` normalmente, sem intervenção manual.

O modelo (`app/modules/whatsapp_inbox/models.py::WhatsappMessage.meta_media_id`) não mudou —
só a migration que a cria.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0055"
down_revision: str | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_messages", sa.Column("meta_media_id", sa.String(128), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("whatsapp_messages", "meta_media_id")
