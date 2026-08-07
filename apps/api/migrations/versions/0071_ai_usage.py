"""Ledger de uso de IA

Revision ID: 0071
Revises: 0070
Create Date: 2026-08-06

Sem backfill — o consumo passado não foi guardado por ninguém (cinco dos seis módulos
descartavam os tokens) e não tem como ser reconstruído. A conta vale a partir daqui.

Só DDL, então a armadilha de RLS no backfill (ver 0046/0066/0067/0068/0069) não se aplica.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0071"
down_revision: str | None = "0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_usage",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("task", sa.String(length=48), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cache_creation_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_ai_usage_user_id", "ai_usage", ["user_id"])
    op.create_index("ix_ai_usage_task", "ai_usage", ["task"])
    # A pergunta que este ledger existe para responder é "quanto este tenant gastou no período".
    # Sem o índice composto ela vira varredura assim que a tabela crescer — e ela cresce a cada
    # chamada de IA, não a cada operação de negócio.
    op.create_index("ix_ai_usage_tenant_created", "ai_usage", ["tenant_id", "created_at"])

    op.execute("ALTER TABLE ai_usage ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ai_usage FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON ai_usage
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )


def downgrade() -> None:
    op.drop_table("ai_usage")
