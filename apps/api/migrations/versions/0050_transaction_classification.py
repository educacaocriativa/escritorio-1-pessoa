"""transactions: classificação (plano de contas + centro de custo + competência) — St. 5.10

Revision ID: 0050
Revises: 0049
Create Date: 2026-07-14

Estende a classificação estrutural (plano de contas/centro de custo), já usada por
payables/charges desde 5.1/5.2/5.5, para `transactions` (Carteira). Motivação: vendas lançadas
direto em "Registrar venda" (ou por Produtos & Checkout) nunca passam por um Payable/Charge, então
ficavam INVISÍVEIS pro DRE — a Carteira não tinha nenhum vínculo de classificação.

Estritamente ADITIVA: só colunas NULLABLE, sem backfill (mesmo racional do cost_center_id em 0048 —
`chart_account_id`/`cost_center_id` NULL tem significado próprio: "sem categoria"/"não atribuído").
`competence_date` também nasce NULL nos legados; a query da DRE faz
`COALESCE(competence_date, date(created_at))` em runtime, então não precisa de backfill (diferente
do 0046, que tinha `due_date` como fallback fixo já existente para popular a coluna).

Sem FK dura (mesmo padrão do projeto: nenhuma FK explícita entre tabelas de negócio). RLS +
validação em app garantem a integridade lógica.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("competence_date", sa.Date(), nullable=True))
    op.add_column(
        "transactions", sa.Column("chart_account_id", sa.String(length=36), nullable=True)
    )
    op.add_column(
        "transactions", sa.Column("cost_center_id", sa.String(length=36), nullable=True)
    )
    op.create_index(
        "ix_transactions_competence_date", "transactions", ["tenant_id", "competence_date"]
    )
    op.create_index(
        "ix_transactions_cost_center_id", "transactions", ["tenant_id", "cost_center_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_cost_center_id", table_name="transactions")
    op.drop_index("ix_transactions_competence_date", table_name="transactions")
    op.drop_column("transactions", "cost_center_id")
    op.drop_column("transactions", "chart_account_id")
    op.drop_column("transactions", "competence_date")
