"""bank_balance_checkpoints: a VERDADE EXTERNA do saldo (plano 3) + RLS — Story 8.4

Revision ID: 0060
Revises: 0059
Create Date: 2026-07-29

Terceiro e último elo da Onda 1 do Epic 8 (Controle Bancário e Conferência). down_revision=**0059**.

  NOTA DE ENCADEAMENTO: o head foi CONFIRMADO programaticamente no momento da implementação
  (`ScriptDirectory.get_heads() == ['0059']`, 2026-07-29), não deduzido do design nem do epic — o
  epic §5 mapeia "Onda 1 → 0058", mas a onda tem TRÊS tabelas em três stories e portanto consome
  três revisions (8.2 → 0058, 8.3 → 0059, 8.4 → **0060**). O que é lei é encadear no head REAL.
  As três migrations da onda são estritamente SERIAIS: duas delas com o mesmo `down_revision`
  produziriam MÚLTIPLOS heads, `alembic upgrade head` falharia com "multiple heads" e a suíte
  `rls_e2e` inteira cairia junto — não só esta story. Mesma lição escrita na `0049_investments.py`.

Estritamente ADITIVA: cria UMA tabela nova (com RLS). NÃO altera nenhuma tabela existente e NÃO faz
backfill — ZERO linhas são lidas ou escritas por esta migration.

  ⚠️ ARMADILHA QUE **NÃO** SE APLICA AQUI, MAS QUE ESTE ARQUIVO VAI ENSINAR A QUEM O COPIAR:
  a migration roda como o papel dono NÃO-superusuário `e1p_app`, **sem** a GUC
  `app.current_tenant_id`. Sob `FORCE ROW LEVEL SECURITY`, qualquer `UPDATE`/`SELECT` direto numa
  tabela de negócio é filtrado a **ZERO LINHAS, em silêncio** — e o SQLite dos testes unitários não
  pega isso (ver `0046_ledger_classification.py`, que desabilita a RLS na janela do backfill e
  reabilita depois). Esta migration não faz backfill algum, então o footgun não a atinge. O aviso
  segue aqui porque a Onda 2 (design §6.2) **vai** fazer backfill e vai copiar este esqueleto:
  copiar a ESTRUTURA é correto; copiar a AUSÊNCIA de disciplina de backfill, não.

- bank_balance_checkpoints: tabela nova de NEGÓCIO (RLS). Cada linha é o usuário (ou, na Onda 3, o
  `<LEDGERBAL>` do arquivo do banco) dizendo *"o saldo desta conta, no FIM deste dia, era X"*.
  É a tabela que torna a conferência possível **sem importação nenhuma** (design §2.4) e o motivo
  de a Onda 1 entregar valor sozinha, antes de qualquer parser existir.

**`reference_date` é `DATE`, jamais `TIMESTAMP`** (design §2.4, `CLAUDE.md` §6.0): é uma data de
calendário e significa o saldo ao FIM daquele dia — exatamente a janela que `derived_balance` usa
com `until=reference_date` (inclusivo). Guardar hora convidaria a conversão UTC↔local que fez
eventos sumirem da Agenda, e aqui o sintoma seria pior: uma divergência inventada no relatório.

**`balance_cents` é `BIGINT` e PODE SER NEGATIVO** (conta no limite / cheque especial). Sem
`CheckConstraint` de sinal, de propósito.

**Referências SOLTAS, sem FK dura** (`bank_account_id`, `import_batch_id`): padrão do projeto
(`charges.client_id`, `payables.cost_center_id`) — a integridade é validada no service, sob RLS.
`import_batch_id` nasce sempre NULL nesta onda; só a Onda 3 escreve nele.

**O índice único merece atenção:** `uq_bank_checkpoint_day` é ÚNICO **total** (não parcial) em
`(tenant_id, bank_account_id, reference_date, origin)`, com `tenant_id` como PRIMEIRA coluna pelo
mesmo motivo da `0058`/`0059`: índice único é GLOBAL e não respeita RLS — sem o tenant na frente, o
tenant B levaria um 409 por causa de um dado do tenant A (bug **e** vazamento de existência).
`origin` entra na chave **de propósito**: o saldo declarado pelo usuário e o saldo lido do arquivo,
para o MESMO dia, são dois fatos independentes e podem coexistir (design §2.4).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0060"
down_revision: str | None = "0059"
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
        "bank_balance_checkpoints",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        # Referência SOLTA (sem FK dura) — validada no service via `get_account`, sob RLS.
        sa.Column("bank_account_id", sa.String(36), nullable=False),
        # DATE, jamais TIMESTAMP — "o saldo NO FIM deste dia". Ver a nota no topo do arquivo.
        sa.Column("reference_date", sa.Date(), nullable=False),
        # PODE ser negativo (cheque especial). BigInteger, centavos, nunca float.
        sa.Column("balance_cents", sa.BigInteger(), nullable=False),
        # Eixo B da procedência (design §1.3.1): "por qual PORTA este saldo externo entrou".
        # manual|ofx — nesta onda SEMPRE 'manual' (a API recusa 'ofx' com 422); a Onda 3 escreve
        # 'ofx' a partir do <LEDGERBAL> do arquivo. NÃO confundir com o eixo A (`*_origem`,
        # `app/core/money_planes.py`), que responde "de qual PLANO de dinheiro o número vem".
        sa.Column("origin", sa.String(12), nullable=False),
        # Sempre NULL nesta onda: só a importação (Onda 3) preenche.
        sa.Column("import_batch_id", sa.String(36), nullable=True),
        # Quem declarou (user_id). NULL para linha nascida de importação automática.
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_bank_checkpoints_tenant_id", "bank_balance_checkpoints", ["tenant_id"]
    )
    op.create_index(
        "uq_bank_checkpoint_day",
        "bank_balance_checkpoints",
        ["tenant_id", "bank_account_id", "reference_date", "origin"],
        unique=True,
    )
    _enable_rls("bank_balance_checkpoints")


def downgrade() -> None:
    op.drop_index("uq_bank_checkpoint_day", table_name="bank_balance_checkpoints")
    op.drop_index("ix_bank_checkpoints_tenant_id", table_name="bank_balance_checkpoints")
    op.drop_table("bank_balance_checkpoints")
