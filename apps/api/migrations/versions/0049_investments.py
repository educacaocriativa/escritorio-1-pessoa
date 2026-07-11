"""investments: conta de investimento (rendimento, rentabilidade) + RLS — Story 5.6

Revision ID: 0049
Revises: 0048
Create Date: 2026-07-11

Sexto elo do Epic 5. down_revision=**0048**.

  NOTA DE ENCADEAMENTO: o rascunho da story sugeria `down_revision=0045` ("depende só de 5.1, pode
  rodar em paralelo com 5.2/5.4/5.5"). Isso valia quando a 5.6 poderia entrar antes/junto das
  demais. Como 5.1→5.5 JÁ estão aplicadas (0048 é o head real da cadeia), encadear em 0045 criaria
  MÚLTIPLOS heads a partir de 0045 → `alembic upgrade head` falharia com "multiple heads". Por isso
  esta migration encadeia LINEARMENTE após 0048 (a ORDEM é o que importa — a 5.6 depende do grupo
  FINANCEIRO do plano de contas da 5.1, que 0048 já supera). Aplica limpo na cadeia
  0045→0046→0047→0048→0049. (Mesma correção de encadeamento documentada na 0048.)

Estritamente ADITIVA: cria UMA tabela nova (com RLS). NÃO altera nenhuma tabela existente e NÃO faz
backfill — logo o footgun do backfill silencioso sob FORCE-RLS (documentado na 0046) não se aplica.

- investment_accounts: tabela nova de NEGÓCIO (RLS) — id, tenant_id, name, kind (tipo de aplicação,
  texto livre), index_rate_label (indexador/taxa, rótulo), principal_cents/accrued_yield_cents
  (BigInteger, centavos), opened_at, timestamps.

O RENDIMENTO em si NÃO tem tabela própria: cada lançamento reusa a tabela `charges` (Contas a
Receber) já baixada, marcada por `external_ref='investment:<id>'` — decisão técnica da story (Task
3), sem coluna nova em charges. Ver `app/modules/investments/service.py`.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
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
        "investment_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False, server_default=""),
        sa.Column("index_rate_label", sa.String(64), nullable=False, server_default=""),
        sa.Column("principal_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("accrued_yield_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("opened_at", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_investment_accounts_tenant_id", "investment_accounts", ["tenant_id"])
    _enable_rls("investment_accounts")


def downgrade() -> None:
    op.drop_index("ix_investment_accounts_tenant_id", table_name="investment_accounts")
    op.drop_table("investment_accounts")
