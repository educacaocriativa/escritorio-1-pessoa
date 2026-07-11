"""charges: campos aditivos do gateway de pagamento real (Asaas)

Adiciona colunas NULLABLE (não quebra linhas existentes — mesmo padrão aditivo da 0029) para
auditoria/suporte do gateway real: qual provedor gerou a cobrança, o id dela no provedor e o
último status bruto recebido pelo webhook. Cobranças via stub permanecem com estes campos NULL.

Revision ID: 0033
Revises: 0031
Create Date: 2026-07-10
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("charges", sa.Column("gateway_provider", sa.String(20), nullable=True))
    op.add_column("charges", sa.Column("gateway_charge_id", sa.String(64), nullable=True))
    op.add_column("charges", sa.Column("gateway_status_raw", sa.String(40), nullable=True))


def downgrade() -> None:
    op.drop_column("charges", "gateway_status_raw")
    op.drop_column("charges", "gateway_charge_id")
    op.drop_column("charges", "gateway_provider")
