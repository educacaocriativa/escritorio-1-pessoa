"""agenda_events ganha google_account_email — de QUAL conta Google veio o vínculo

Revision ID: 0086
Revises: 0085
Create Date: 2026-09-05

Por quê: `agenda_events.google_event_id` é escrito em dois lugares — o espelho criado por
`agenda/service.py::create_event` e o pull de `google_calendar/sync.py::_apply_item` — e nunca
registrou de QUAL conta Google aquele id veio. Quando o tenant desconecta (o `disconnect`
manual ou o descarte automático do token revogado, ambos em `google_calendar/service.py`) e
depois reconecta com OUTRA conta, os ids antigos sobrevivem apontando para um calendário que
não é mais dele.

`nullable=True` e SEM `server_default`, DE PROPÓSITO — `NULL` aqui tem SIGNIFICADO SEMÂNTICO:
PROCEDÊNCIA DESCONHECIDA (linha legada, gravada antes desta coluna existir). É o que permite à
limpeza de reconexão (`google_calendar/service.py::_invalidar_vinculos_de_outra_conta`) deixar
as linhas legadas INTACTAS em vez de apagá-las às cegas — apagar às cegas reintroduziria a
duplicação de eventos no próximo sync para os dados que já existem.

SEM BACKFILL, mesma disciplina das migrations 0084/0085: DDL puro. Um `UPDATE` aqui rodaria
sob FORCE RLS sem `app.current_tenant_id` definido, seria filtrado a ZERO linhas e "passaria"
em silêncio — o modo de falha que já mordeu este repo. As linhas legadas se AUTOCURAM sozinhas
no primeiro sync bem-sucedido: o ramo de update de `_apply_item` carimba a conta.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0086"
down_revision: str | None = "0085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agenda_events", sa.Column("google_account_email", sa.String(255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agenda_events", "google_account_email")
