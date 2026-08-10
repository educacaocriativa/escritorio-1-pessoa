"""O saque da Carteira vira fato, e ganha perna bancária (Epic 8, Onda 3)

Revision ID: 0077
Revises: 0076
Create Date: 2026-08-09

**Por quê.** `request_payout` marcava `withdrawn` e não deixava registro. Sem uma linha
representando o saque não existe `origin_id` para o `sync_origin_movement` apontar — e sem isso o
payout não pode virar `bank_transaction`, o que mantém aberto o termo **P4** da pré-condição do
gate do épico. Enquanto P4 for não-vazio numa janela, a divergência daquele ciclo **não pode ser
lida**, e nenhuma onda é liberada nem morta com base nela.

⚠️ **NENHUM `UPDATE`, e a ausência é a razão de esta migration ser segura.** As seis armadilhas
registradas neste repo (`0046`, `0066`, `0067`, `0068`, `0069`, `0073`) são todas a mesma: um
`UPDATE` de backfill filtrado em silêncio pela RLS, completando com sucesso APARENTE e invisível
para o SQLite da suíte. `CREATE TABLE` e `ADD COLUMN` são DDL — a RLS não os alcança.

**As `Transaction` já sacadas ficam com `payout_id IS NULL` para sempre, e isso não é dívida.**
Elas não têm saque a que pertencer, porque o saque nunca foi registrado. Inventar um `Payout`
retroativo seria escrever história sem testemunha — a manobra que a Onda 2b-ii recusou.

⚠️ **`bank_transaction_id` nasce `NOT NULL`.** É a invariante da onda (P4 = 0) fail-closed no
banco, e não uma escolha estética. Ver a docstring de `wallet.models.Payout`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0077"
down_revision: str | None = "0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payouts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("bank_account_id", sa.String(length=36), nullable=False),
        sa.Column("bank_transaction_id", sa.String(length=36), nullable=False),
        sa.Column("actor", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_payouts_paid_on", "payouts", ["tenant_id", "paid_on"])

    op.execute("ALTER TABLE payouts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE payouts FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON payouts
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )

    op.add_column("transactions", sa.Column("payout_id", sa.String(length=36), nullable=True))


def downgrade() -> None:
    # O que se perde é o REGISTRO do saque e o vínculo com o razão bancário — o payout volta a ser
    # uma troca de status sem testemunha e o termo P4 do gate reabre. Fica escrito aqui em vez de
    # ser descoberto no meio de um rollback.
    op.drop_column("transactions", "payout_id")
    op.drop_index("ix_payouts_paid_on", table_name="payouts")
    op.drop_table("payouts")
