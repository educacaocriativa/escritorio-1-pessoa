"""DNA da Empresa — respostas do dono

Revision ID: 0076
Revises: 0075
Create Date: 2026-08-08

⚠️ **Nasceu como `0075` e foi RENUMERADA.** Esta migration e a `0075_investment_bank_account.py`
(Epic 8, Onda 2b-i) foram escritas em paralelo, as duas a partir de `0074`, e as duas
reivindicavam o mesmo id. A outra mergeou primeiro (PR #100), então esta renumerou — **quem
mergeia depois renumera**, e antes do merge, nunca depois: duas revisions com o mesmo id fazem
`alembic upgrade head` escolher uma em silêncio, e a outra some sem erro nenhum.

Numerar `0076` preventivamente, antes de a outra mergear, teria sido pior: a cadeia deste branch
ficaria `0074 → 0076` com o elo faltando, impossível de rodar e de testar. É a terceira vez que
este repositório encosta nessa armadilha (ver a `0072`).

Sem backfill: não existe resposta anterior a esta migration, então a armadilha da RLS no backfill
(ver 0046/0066/0067/0068/0069) não se aplica. Só DDL.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0076"
down_revision: str | None = "0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dna_answers",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("question_key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answered_by", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # O upsert depende desta constraint: uma resposta por pergunta por tenant.
        sa.UniqueConstraint("tenant_id", "question_key", name="uq_dna_answer"),
    )
    op.create_index("ix_dna_answers_question_key", "dna_answers", ["question_key"])

    op.execute("ALTER TABLE dna_answers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE dna_answers FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON dna_answers
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )


def downgrade() -> None:
    op.drop_table("dna_answers")
