"""bank_transactions: a linha de extrato (plano 3 do dinheiro) + RLS — Story 8.3

Revision ID: 0059
Revises: 0058
Create Date: 2026-07-29

Segundo elo do Epic 8 (Controle Bancário e Conferência), Onda 1. down_revision=**0058**.

  NOTA DE ENCADEAMENTO: o head foi CONFIRMADO programaticamente no momento da implementação
  (`ScriptDirectory.get_heads() == ['0058']`, 2026-07-29), não deduzido do design. Mesma disciplina
  da `0058_bank_accounts.py` e a lição escrita na `0049_investments.py`: encadear num revision
  antigo cria MÚLTIPLOS heads e `alembic upgrade head` falha com "multiple heads" — o que derrubaria
  a suíte `rls_e2e` inteira, não só esta story. A Onda 1 consome TRÊS revisions (8.2 → 0058,
  8.3 → 0059, 8.4 → 0060): a granularidade é uma migration por story que cria tabela.

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

- bank_transactions: tabela nova de NEGÓCIO (RLS) — cada linha é um movimento do extrato.
  `amount_cents` é **assinado** (+ crédito / − débito), então o saldo derivado é `SUM()` puro, sem
  `CASE`. `posted_at` é **DATE** e nunca `TIMESTAMP` (design §3.3): extrato brasileiro é por dia, e
  guardar hora só convidaria a conversão UTC↔local que fez eventos sumirem da Agenda
  (`CLAUDE.md` §6.0). Ver `app/modules/bank/models.py` para as quatro invariantes do modelo.

**Colunas criadas AGORA e escritas só na Onda 3/4** (`fitid`, `balance_after_cents`,
`pix_end_to_end_id`, `fiscal_document_ref`, `import_batch_id`, `transfer_id`): design §7.3 —
*"é barato guardar cedo e caro descobrir tarde"*, porque o dado histórico do banco não volta.
Todas nullable ou com default, nenhuma exigida no lançamento manual. `dedup_hash` é a exceção que
NASCE preenchida: é `NOT NULL` e carrega a constraint única, então a primeira linha inserida já
precisa de um valor (ver `service._manual_dedup_hash`).

**Os dois índices que merecem atenção:**
- `ix_bank_transactions_status` é **PARCIAL** (`WHERE status <> 'matched'`): a conferência só varre
  o que não bateu, e o índice parcial mantém pequeno justo o que cresce (design §2.2);
- `uq_bank_transactions_dedup` é **ÚNICO** em `(tenant_id, bank_account_id, dedup_hash)`, com
  `tenant_id` como PRIMEIRA coluna pelo mesmo motivo da `0058`: índice único é GLOBAL e não respeita
  RLS — sem o tenant na frente, o tenant B levaria um 409 por causa de um dado do tenant A (bug
  **e** vazamento de existência).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0059"
down_revision: str | None = "0058"
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
        "bank_transactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        # Referência SOLTA (sem FK dura), padrão do projeto: a integridade é validada no service
        # sob RLS. Ver a docstring de `app/modules/bank/service.py`.
        sa.Column("bank_account_id", sa.String(36), nullable=False),
        # DATE, jamais TIMESTAMP — ver a nota de `posted_at` no topo deste arquivo.
        sa.Column("posted_at", sa.Date(), nullable=False),
        # COM SINAL: + crédito (entrada), − débito (saída). Nunca zero (guarda no service).
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        # O que o banco disse — IMUTÁVEL, é a prova documental (design §2.2).
        sa.Column("raw_description", sa.Text(), nullable=False, server_default=""),
        # O que o usuário (Onda 1) ou a IA (Onda 4, sempre com confirmação) chamou o movimento.
        sa.Column("user_description", sa.Text(), nullable=False, server_default=""),
        # <FITID> do OFX — NULL no manual e no CSV. Guardado p/ diagnóstico e p/ detectar
        # reciclagem de FITID por banco (Onda 3).
        sa.Column("fitid", sa.String(255), nullable=True),
        # Mecanismo UNIVERSAL de idempotência (CSV não tem FITID, manual não tem) — §4.4.
        sa.Column("dedup_hash", sa.String(64), nullable=False),
        # Saldo após o movimento, quando o arquivo do banco trouxer (Onda 3).
        sa.Column("balance_after_cents", sa.BigInteger(), nullable=True),
        # Contraparte (§7, rastreabilidade tributária) — TODOS opcionais.
        # ⚠️ PII de terceiro que NUNCA contratou com a e1p: a partir da Onda 3/4 estes campos só
        # podem ir ao Claude via `core/anonymizer` (Regra de Ouro nº 2, REQ-18, design §7.4).
        sa.Column("counterparty_name", sa.String(160), nullable=False, server_default=""),
        sa.Column("counterparty_document", sa.String(20), nullable=False, server_default=""),
        sa.Column("pix_end_to_end_id", sa.String(40), nullable=True),
        sa.Column("operation_nature", sa.String(24), nullable=True),
        sa.Column("fiscal_document_ref", sa.String(64), nullable=True),
        # ofx|csv|manual|transfer|yield|payout — nesta onda SEMPRE 'manual' (fixado no service,
        # nunca aceito do cliente).
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("import_batch_id", sa.String(36), nullable=True),
        sa.Column("transfer_id", sa.String(36), nullable=True),
        # unmatched|partial|matched|ignored. Nesta onda só `unmatched` e `ignored` são escritos:
        # `partial`/`matched` pertencem ao `_refresh_status` da conciliação (Onda 4).
        sa.Column("status", sa.String(16), nullable=False, server_default="unmatched"),
        sa.Column("ignored_reason", sa.String(120), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_bank_transactions_tenant_id", "bank_transactions", ["tenant_id"])
    # O índice de trabalho: toda leitura desta tabela é "os movimentos DESTA conta NESTA janela".
    op.create_index(
        "ix_bank_transactions_account_date",
        "bank_transactions",
        ["tenant_id", "bank_account_id", "posted_at"],
    )
    op.create_index(
        "ix_bank_transactions_status",
        "bank_transactions",
        ["tenant_id", "status"],
        postgresql_where=sa.text("status <> 'matched'"),
        sqlite_where=sa.text("status <> 'matched'"),
    )
    op.create_index(
        "uq_bank_transactions_dedup",
        "bank_transactions",
        ["tenant_id", "bank_account_id", "dedup_hash"],
        unique=True,
    )
    _enable_rls("bank_transactions")


def downgrade() -> None:
    op.drop_index("uq_bank_transactions_dedup", table_name="bank_transactions")
    op.drop_index("ix_bank_transactions_status", table_name="bank_transactions")
    op.drop_index("ix_bank_transactions_account_date", table_name="bank_transactions")
    op.drop_index("ix_bank_transactions_tenant_id", table_name="bank_transactions")
    op.drop_table("bank_transactions")
