"""Vínculo `contract_id` (Payable/Charge) + `fixed_costs_allocated_cents` (Contract) — Story 5.4

Revision ID: 0047
Revises: 0046
Create Date: 2026-07-11

Quarto elo do Epic 5 (5.1 chart_accounts → 5.2 classificação → 5.3 DRE → **5.4** lucratividade
por contrato). down_revision=0046 (Story 5.2). A 5.4 NÃO depende de 5.5/5.6 — pode rodar em
paralelo com elas após a 5.2; se, no merge, 0046 não for mais o head real, religar o encadeamento
(a ORDEM é o que importa: esta migration nasce DEPOIS da 5.2, que traz `chart_account_id`).

Estritamente ADITIVA: só colunas NULLABLE, SEM backfill e SEM tabela nova. O `Contract` já
existente vira o eixo financeiro "projeto" (decisão do fundador — não se cria `financial_projects`).

- payables: ganha `contract_id` (VARCHAR(36) NULL) — vínculo opcional ao Contract.
- charges:  ganha `contract_id` (VARCHAR(36) NULL) — vínculo opcional ao Contract.
- contracts: ganha `fixed_costs_allocated_cents` (BIGINT NULL) — custo fixo atribuído (manual),
  usado no break-even da DRE do contrato. Distinto do overhead rateado (só-leitura, nunca gravado).

Sem FK dura em `contract_id` (mesmo padrão do projeto: nenhuma FK explícita entre tabelas de
negócio, ex.: charges.client_id). RLS + validação em app garantem a integridade lógica.

`contract_id IS NULL` = bucket implícito "Empresa" (overhead) por CONVENÇÃO DE AUSÊNCIA — NÃO se
grava um valor sentinela. Por isso NÃO há backfill: lançamentos legados nascem com contract_id NULL
e são lidos como "Empresa" na camada analítica. Como não há UPDATE, NÃO é preciso desabilitar a
RLS temporariamente (o footgun do backfill silencioso sob FORCE-RLS documentado na 0046 não se
aplica aqui — esta migration só faz DDL aditivo).

Índices `(tenant_id, contract_id)` aceleram a DRE por contrato (filtra por contract_id sob a
predicate de tenant da RLS) — mesmo padrão composto dos índices de competência da 0046.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("payables", sa.Column("contract_id", sa.String(length=36), nullable=True))
    op.add_column("charges", sa.Column("contract_id", sa.String(length=36), nullable=True))
    op.add_column(
        "contracts",
        sa.Column("fixed_costs_allocated_cents", sa.BigInteger(), nullable=True),
    )

    op.create_index("ix_payables_contract_id", "payables", ["tenant_id", "contract_id"])
    op.create_index("ix_charges_contract_id", "charges", ["tenant_id", "contract_id"])


def downgrade() -> None:
    op.drop_index("ix_charges_contract_id", table_name="charges")
    op.drop_index("ix_payables_contract_id", table_name="payables")
    op.drop_column("contracts", "fixed_costs_allocated_cents")
    op.drop_column("charges", "contract_id")
    op.drop_column("payables", "contract_id")
