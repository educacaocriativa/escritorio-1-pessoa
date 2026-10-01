"""lead_ingest_records: idempotência da ingestão de leads, única por (tenant, chave)

Revision ID: 0089
Revises: 0088
Create Date: 2026-09-30

Tabela de NEGÓCIO com RLS (mesma policy `tenant_isolation` de todas): guarda o payload bruto,
com contato e valores. A restrição única `(tenant_id, chave_idempotencia)` é a idempotência —
no banco, não em código: dois reenvios simultâneos da Kiwify serializam no índice e o segundo
falha, em vez de os dois passarem pela checagem antes de qualquer um gravar.

DDL puro, sem UPDATE (a armadilha das 0046/0066/0067/0068/0069/0073 não se aplica).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0089"
down_revision: str | None = "0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lead_ingest_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("chave_idempotencia", sa.String(200), nullable=False),
        sa.Column("evento", sa.String(32), nullable=False),
        sa.Column("ocorrido_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "client_id",
            sa.String(36),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("tags_descartadas", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("concluido_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "tenant_id", "chave_idempotencia", name="uq_lead_ingest_tenant_chave"
        ),
    )
    op.execute("ALTER TABLE lead_ingest_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE lead_ingest_records FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON lead_ingest_records
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )


def downgrade() -> None:
    op.drop_table("lead_ingest_records")
