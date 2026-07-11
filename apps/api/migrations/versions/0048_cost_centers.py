"""cost_centers: centro de custo (2ª dimensão) + RLS + cost_center_id (payables/charges) — St. 5.5

Revision ID: 0048
Revises: 0047
Create Date: 2026-07-11

Quinto elo do Epic 5 (5.1 chart_accounts → 5.2 classificação → 5.3 DRE → 5.4 lucratividade por
contrato → **5.5** centro de custo). down_revision=**0047**.

  NOTA DE ENCADEAMENTO: o rascunho da story sugeria `down_revision=0046` ("5.5 não depende de
  5.4/5.6, pode rodar em paralelo"). Isso valia quando 5.5 poderia entrar ANTES/junto da 5.4. Como
  a 5.4 JÁ está `Done` (0047 é o head real da cadeia), encadear em 0046 criaria DOIS heads a partir
  de 0046 (0047 e 0048) → `alembic upgrade head` falharia com "multiple heads". Por isso esta
  migration encadeia LINEARMENTE após 0047 (a ORDEM é o que importa — 5.5 depende da 5.2 para o
  padrão de coluna nullable, o que 0047 já supera). Aplica limpo na cadeia
  0045→0046→0047→0048.

Estritamente ADITIVA: cria uma tabela nova (com RLS) e adiciona SÓ colunas NULLABLE, SEM backfill.

- cost_centers: tabela nova de NEGÓCIO (RLS) — id, tenant_id, name, kind (texto livre), archived_at,
  timestamps. `UniqueConstraint(tenant_id, name)`.
- payables: ganha `cost_center_id` (VARCHAR(36) NULL) — vínculo opcional à 2ª dimensão.
- charges:  ganha `cost_center_id` (VARCHAR(36) NULL) — vínculo opcional à 2ª dimensão.

Sem FK dura em `cost_center_id` (mesmo padrão do projeto: nenhuma FK explícita entre tabelas de
negócio, ex.: charges.client_id/contract_id). RLS + validação em app garantem a integridade lógica.

`cost_center_id IS NULL` = "Não atribuído" por CONVENÇÃO DE AUSÊNCIA — NÃO se grava sentinela. Por
isso NÃO há backfill: lançamentos legados nascem com cost_center_id NULL e são lidos como "Não
atribuído" na camada analítica. Como não há UPDATE, NÃO é preciso desabilitar a RLS temporariamente
(o footgun do backfill silencioso sob FORCE-RLS documentado na 0046 não se aplica — só DDL aditivo).

Índices `(tenant_id, cost_center_id)` aceleram o filtro/cruzamento por centro de custo (sob a
predicate de tenant da RLS) — mesmo padrão composto dos índices de competência/contrato (0046/0047).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
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
        "cost_centers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="outro"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "name", name="uq_cost_center_tenant_name"),
    )
    op.create_index("ix_cost_centers_tenant_id", "cost_centers", ["tenant_id"])
    _enable_rls("cost_centers")

    # Vínculo opcional (2ª dimensão) nos lançamentos — aditivo/nullable, sem backfill.
    op.add_column("payables", sa.Column("cost_center_id", sa.String(length=36), nullable=True))
    op.add_column("charges", sa.Column("cost_center_id", sa.String(length=36), nullable=True))
    op.create_index("ix_payables_cost_center_id", "payables", ["tenant_id", "cost_center_id"])
    op.create_index("ix_charges_cost_center_id", "charges", ["tenant_id", "cost_center_id"])


def downgrade() -> None:
    op.drop_index("ix_charges_cost_center_id", table_name="charges")
    op.drop_index("ix_payables_cost_center_id", table_name="payables")
    op.drop_column("charges", "cost_center_id")
    op.drop_column("payables", "cost_center_id")
    op.drop_index("ix_cost_centers_tenant_id", table_name="cost_centers")
    op.drop_table("cost_centers")
