"""chart_accounts: plano de contas hierárquico por grupo DRE + RLS (Story 5.1)

Revision ID: 0045
Revises: 0044
Create Date: 2026-07-11

Primeira migration do Epic 5. down_revision=0044 (head atual da cadeia linearizada
0031->0033->0039->0040->0041->0042->0044). Se, no merge, 0044 não for mais o head real (outra
story do Epic 5 entrou antes), religar o encadeamento para o novo head — mesmo ajuste já feito
neste repo ("fix: corrige down_revision..."). A ORDEM de dependência é o que importa: 5.1 nasce
ANTES de 5.2 (que referencia chart_account_id).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )


def upgrade() -> None:
    op.create_table(
        "chart_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("grupo_dre", sa.String(20), nullable=False),
        sa.Column("categoria", sa.String(80), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id",
            "grupo_dre",
            "categoria",
            name="uq_chart_account_tenant_group_categoria",
        ),
    )
    op.create_index("ix_chart_accounts_tenant_id", "chart_accounts", ["tenant_id"])
    op.create_index(
        "ix_chart_accounts_tenant_grupo", "chart_accounts", ["tenant_id", "grupo_dre"]
    )
    _enable_rls("chart_accounts")


def downgrade() -> None:
    op.drop_table("chart_accounts")
