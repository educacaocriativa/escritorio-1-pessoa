"""payables/charges/transactions ganham documento e observacoes

Revision ID: 0085
Revises: 0084
Create Date: 2026-09-01

Por quê: as telas de lançamento (Registrar venda, Nova cobrança, Nova conta a pagar) não tinham
onde guardar o número do documento (nota fiscal, recibo...) nem uma observação livre — só existia
`description`, que funciona como título curto da linha, não como anotação.

`server_default=''` PERMANENTE (mesma disciplina da migration 0084): DDL puro, sem backfill sob
FORCE RLS. Os três `*Create` (`PayableCreate`/`ChargeCreate`/`TransactionCreate`) já default para
"" quando omitidos, então o server_default só cobre a criação da coluna em cima de linhas
existentes — nenhum caminho de escrita depende dele depois disso.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0085"
down_revision: str | None = "0084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("payables", "charges", "transactions")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table, sa.Column("documento", sa.String(64), nullable=False, server_default="")
        )
        op.add_column(
            table, sa.Column("observacoes", sa.Text(), nullable=False, server_default="")
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "observacoes")
        op.drop_column(table, "documento")
