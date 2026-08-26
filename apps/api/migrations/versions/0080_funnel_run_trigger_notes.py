"""funnel_runs.trigger_notes: snapshot dos campos do formulário QUE INSCREVEU esta jornada.

Revision ID: 0080
Revises: 0079
Create Date: 2026-08-26

`{{cliente.notas}}` (usado no nó de e-mail/WhatsApp) lia `client.notes` — mas `absorb_lead`
(crm/service.py) só preenche `notes` na CRIAÇÃO do contato; quem retorna pelo mesmo canal
(mesmo telefone/e-mail) nunca sobrescreve `notes`, de propósito, pra não apagar edição manual
do dono. Resultado: o e-mail de alerta de um lead que já existia saía com os campos do
PRIMEIRO envio (ou vazio, se o contato nasceu de outro jeito). `trigger_notes` é o snapshot do
envio QUE DISPAROU esta jornada especificamente — `engine.enroll` grava, e os nós de
comunicação passam a preferir isto a `client.notes`.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0080"
down_revision: str | None = "0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "funnel_runs",
        sa.Column("trigger_notes", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("funnel_runs", "trigger_notes")
