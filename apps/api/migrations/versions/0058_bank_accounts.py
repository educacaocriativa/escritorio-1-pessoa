"""bank_accounts: a conta bancária do usuário (plano 3 do dinheiro) + RLS — Story 8.2

Revision ID: 0058
Revises: 0057
Create Date: 2026-07-29

Primeiro elo do Epic 8 (Controle Bancário e Conferência), Onda 1. down_revision=**0057**.

  NOTA DE ENCADEAMENTO: o head foi CONFIRMADO no momento da implementação (`ScriptDirectory.
  get_heads() == ['0057']`, 2026-07-29), não fixado a partir do design. É a lição já escrita na
  docstring da `0049_investments.py`: encadear num revision antigo cria MÚLTIPLOS heads e
  `alembic upgrade head` falha com "multiple heads". O design (§2, ratificação D-6) parou de
  carimbar número de revision justamente por isso — a granularidade é **uma migration por story
  que cria tabela**, então a Onda 1 consome três revisions (8.2/8.3/8.4), não uma.

Estritamente ADITIVA: cria UMA tabela nova (com RLS). NÃO altera nenhuma tabela existente e NÃO faz
backfill.

  ⚠️ ARMADILHA QUE **NÃO** SE APLICA AQUI, MAS SE APLICA À PRÓXIMA MIGRATION DESTE MÓDULO:
  a migration roda como o papel dono NÃO-superusuário `e1p_app`, **sem** a GUC
  `app.current_tenant_id`. Sob `FORCE ROW LEVEL SECURITY`, qualquer `UPDATE`/`SELECT` direto numa
  tabela de negócio é filtrado a **ZERO LINHAS, em silêncio** — e o SQLite dos testes unitários não
  pega isso (ver `0046_ledger_classification.py`, que desabilita a RLS na janela do backfill e
  reabilita depois). Esta migration não faz backfill algum, então o footgun não a atinge; o aviso
  está aqui porque a Onda 2 (design §6.2) **vai** fazer backfill e vai copiar este arquivo como
  modelo. Copiar o esqueleto é correto; copiar a AUSÊNCIA de disciplina de backfill, não.

- bank_accounts: tabela nova de NEGÓCIO (RLS) — a conta bancária real do usuário. Saldo é
  DERIVADO (design §3.1), então NÃO existe coluna de saldo: só `opening_balance_cents` +
  `opening_date` (o ponto de partida que o usuário CONFIRMA olhando o app do banco). Ver
  `app/modules/bank/models.py`.

Índice único PARCIAL `uq_bank_accounts_tenant_ident` em (tenant_id, institution_code, branch,
number) `WHERE number <> ''`: impede a mesma conta cadastrada duas vezes (que produziria divergência
crônica na conferência) sem impedir N contas informais sem número ("Caixinha"). `tenant_id` é a
PRIMEIRA coluna porque índice único é GLOBAL e não respeita RLS — sem isso o tenant B receberia um
409 inexplicável por causa de um dado do tenant A (bug **e** vazamento de existência; design §2.1).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0058"
down_revision: str | None = "0057"
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
        "bank_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        # checking|savings|investment|cash (platform_wallet é RESERVADO e recusado pela API)
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("institution", sa.String(120), nullable=False, server_default=""),
        sa.Column("institution_code", sa.String(8), nullable=False, server_default=""),
        sa.Column("branch", sa.String(16), nullable=False, server_default=""),
        sa.Column("number", sa.String(32), nullable=False, server_default=""),
        sa.Column("holder_document", sa.String(20), nullable=False, server_default=""),
        sa.Column("pix_key", sa.String(140), nullable=False, server_default=""),
        sa.Column("opening_balance_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("opening_date", sa.Date(), nullable=False),
        sa.Column(
            "is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_bank_accounts_tenant_id", "bank_accounts", ["tenant_id"])
    op.create_index(
        "uq_bank_accounts_tenant_ident",
        "bank_accounts",
        ["tenant_id", "institution_code", "branch", "number"],
        unique=True,
        postgresql_where=sa.text("number <> ''"),
        sqlite_where=sa.text("number <> ''"),
    )
    _enable_rls("bank_accounts")


def downgrade() -> None:
    op.drop_index("uq_bank_accounts_tenant_ident", table_name="bank_accounts")
    op.drop_index("ix_bank_accounts_tenant_id", table_name="bank_accounts")
    op.drop_table("bank_accounts")
