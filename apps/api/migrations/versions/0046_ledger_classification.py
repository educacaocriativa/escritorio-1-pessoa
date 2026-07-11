"""Classificação de lançamentos + 3 datas (competência/vencimento/pagamento) — Story 5.2

Revision ID: 0046
Revises: 0045
Create Date: 2026-07-11

Segundo elo do Epic 5 (5.1 chart_accounts -> **5.2** -> 5.3/5.4/5.7). down_revision=0045 (a
migration da Story 5.1, que cria `chart_accounts`; `chart_account_id` referencia essa tabela).
Se, no merge, 0045 não for mais o head real, religar o encadeamento — a ORDEM é o que importa
(5.1 nasce ANTES de 5.2).

Estritamente ADITIVA (CR2): só colunas NULLABLE + backfill em UPDATE (nunca NOT NULL sem default).
Não invalida nenhum registro existente (AC2).

- payables: ganha `competence_date` (DATE) e `chart_account_id` (VARCHAR(36)). NÃO ganha `paid_at`
  (já existe desde a Fase 2, setado em mark_paid).
- charges: ganha `competence_date` (DATE), `chart_account_id` (VARCHAR(36)) e `paid_at`
  (TIMESTAMPTZ, campo NOVO — Charge não tinha data de pagamento; só status="paid"+updated_at).

Backfill (AC2, "lançamentos legados continuam válidos"):
- competence_date = due_date (regra do fallback aplicada retroativamente), payables e charges.
- charges.paid_at = updated_at para cobranças já pagas (status='paid'). APROXIMAÇÃO documentada:
  `updated_at` no momento da baixa é o timestamp mais próximo do pagamento real que existe hoje
  para cobranças legadas — não há registro melhor. Cobranças pagas após esta migration recebem o
  `paid_at` exato no service (mark_paid).

Sem FK dura em chart_account_id (mesmo padrão do projeto: nenhuma FK explícita entre tabelas de
negócio, ex. charges.client_id). RLS + validação em app garantem a integridade lógica.

⚠️ O backfill desabilita a RLS temporariamente (ver comentário no upgrade): as tabelas têm FORCE
ROW LEVEL SECURITY e a migration roda sem GUC de tenant, então um UPDATE seria filtrado a zero
linhas. Descoberto na validação e2e em Postgres real (não aparece no SQLite dos testes unitários).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- payables: competência + vínculo de conta (paid_at já existe) ---
    op.add_column("payables", sa.Column("competence_date", sa.Date(), nullable=True))
    op.add_column("payables", sa.Column("chart_account_id", sa.String(length=36), nullable=True))

    # --- charges: competência + vínculo de conta + paid_at (NOVO) ---
    op.add_column("charges", sa.Column("competence_date", sa.Date(), nullable=True))
    op.add_column("charges", sa.Column("chart_account_id", sa.String(length=36), nullable=True))
    op.add_column(
        "charges", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True)
    )

    # --- backfill de legados (AC2) ---
    # ⚠️ CRÍTICO (validado em Postgres real): `payables`/`charges` têm FORCE ROW LEVEL SECURITY e a
    # migration roda como o papel DONO non-superuser (`e1p_app`) SEM a GUC `app.current_tenant_id`
    # setada. Um UPDATE direto seria filtrado pela política RLS (USING tenant_id = current_setting)
    # → current_setting vazio → ZERO linhas visíveis → o backfill viraria um no-op SILENCIOSO
    # (lançamentos legados ficariam com competence_date/paid_at NULL). Por isso desabilitamos a
    # RLS SÓ durante o backfill e a restauramos (ENABLE + FORCE) logo depois. DDL é transacional no
    # Postgres (todo o upgrade 0046 é uma transação), então não há janela de exposição a sessões
    # concorrentes — e a migration roda offline. (Padrão de data-migration sobre tabelas RLS.)
    for table in ("payables", "charges"):
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute(
        "UPDATE payables SET competence_date = due_date WHERE competence_date IS NULL"
    )
    op.execute(
        "UPDATE charges SET competence_date = due_date WHERE competence_date IS NULL"
    )
    # Aproximação documentada: updated_at ~= momento da baixa para cobranças legadas já pagas.
    op.execute(
        "UPDATE charges SET paid_at = updated_at WHERE status = 'paid' AND paid_at IS NULL"
    )

    for table in ("payables", "charges"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # --- índices por competência (usados pela DRE da Story 5.3, que agrega por competência) ---
    op.create_index(
        "ix_payables_competence_date", "payables", ["tenant_id", "competence_date"]
    )
    op.create_index(
        "ix_charges_competence_date", "charges", ["tenant_id", "competence_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_charges_competence_date", table_name="charges")
    op.drop_index("ix_payables_competence_date", table_name="payables")
    op.drop_column("charges", "paid_at")
    op.drop_column("charges", "chart_account_id")
    op.drop_column("charges", "competence_date")
    op.drop_column("payables", "chart_account_id")
    op.drop_column("payables", "competence_date")
