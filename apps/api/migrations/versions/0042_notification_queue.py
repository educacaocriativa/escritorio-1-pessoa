"""notification_queue: fila assíncrona de envios reaproveitando `notifications` (Story 4.3)

Adiciona duas colunas à tabela `notifications` (já de NEGÓCIO / RLS) para transformá-la também
na fila de envios assíncronos: `attempts` (nº de tentativas) e `last_error` (motivo da falha).
Nenhuma mudança de RLS — só ALTER TABLE ADD COLUMN; as políticas da `notifications` (criadas na
migration original da tabela) permanecem intactas. O novo valor de `status` "pending" (enfileirada)
NÃO exige migration: a coluna `status` já é `String(16)` livre, só passa a aceitar mais um valor.

Revision ID: 0042
Revises: 0031
Create Date: 2026-07-10

Coordenação (13 stories em paralelo): o número 0042 foi RESERVADO com exclusividade para esta
story. `down_revision="0031"` era o head no momento do checkout; se, no merge, o head real for
outro, quem integrar deve religar o `down_revision` para o novo head (mesmo ajuste já feito no
commit 16648b3 e antecipado pela Story 4.1 com o número 0040).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0042"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "notifications",
        sa.Column("last_error", sa.String(500), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("notifications", "last_error")
    op.drop_column("notifications", "attempts")
