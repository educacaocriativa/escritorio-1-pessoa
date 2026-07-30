"""A Regra da Origem: chave de origem + os ponteiros de negócio (plano 3) — Story 8.9

Revision ID: 0061
Revises: 0060
Create Date: 2026-07-30

Primeiro elo da **Onda 2** do Epic 8 (a origem do movimento bancário). down_revision=**0060**.

  NOTA DE ENCADEAMENTO: o head foi CONFIRMADO programaticamente no momento da implementação
  (`ScriptDirectory.get_heads() == ['0060']`, 2026-07-30), não deduzido do design nem da story —
  mesma disciplina da `0058`/`0059`/`0060` e a lição escrita na `0049_investments.py`. **O epic não
  fixa número; o head real é lei.** Encadear num revision antigo cria MÚLTIPLOS heads,
  `alembic upgrade head` falha com "multiple heads" e a suíte `rls_e2e` INTEIRA cai junto — não só
  esta story. A Story 8.18 (transferências) também tem migration própria e o epic §6.1 manda
  mergeá-la **por último**, exatamente para não disputar head com esta.

Estritamente ADITIVA: **5 `ADD COLUMN` nullable e 2 `CREATE INDEX`**. Nenhuma tabela é criada,
nenhuma policy de RLS é tocada (as três tabelas envolvidas já têm RLS `FORCE` — `payables` na 0011,
`charges` na 0010, `bank_transactions` na 0059), e **ZERO linhas são lidas ou escritas**: sem
`UPDATE`, sem `SELECT`, sem backfill.

  ⚠️ ARMADILHA QUE **NÃO** SE APLICA AQUI — e a declaração é obrigatória, não decorativa:
  a migration roda como o papel dono NÃO-superusuário `e1p_app`, **sem** a GUC
  `app.current_tenant_id`. Sob `FORCE ROW LEVEL SECURITY`, qualquer `UPDATE`/`SELECT` direto numa
  tabela de negócio é filtrado a **ZERO LINHAS, em silêncio** — e o SQLite dos testes unitários não
  pega isso (ver `0046_ledger_classification.py`, que desabilita a RLS na janela do backfill e
  reabilita depois). **Esta migration não faz backfill algum, e por isso o footgun não a atinge.**
  Herdamos o esqueleto da `0060`, que avisou em voz alta: copiar a ESTRUTURA é correto; copiar a
  AUSÊNCIA de disciplina de backfill, não. O backfill das 45 contas pagas do fundador é MANUAL
  (epic F8) e não é trabalho de migration nenhuma.

**O que cada coluna é** (design `controle-bancario-onda2-design.md` §3.2, §3.3, §3.4):

- `bank_transactions.origin_id VARCHAR(64) NULL` — a **CHAVE DE ORIGEM**, não "o id do lançamento"
  (ratificação §C-3.3). Para origem de perna única (`payable`, `charge`, `yield`, `payout`) ela É o
  id do lançamento; para origem de múltiplas pernas é `f"{id}:{perna}"` (`transfer`, com `out`/`in`
  — Story 8.18). **A largura 64 é decisão de custo assimétrico, não conforto:** `uuid4` (36) +
  `":out"` (4) = 40, em Postgres `VARCHAR(n)` é armazenamento variável (64 e 36 custam o mesmo em
  disco) e errar para menos custaria `ALTER COLUMN` sobre tabela com dado sob `FORCE RLS` — a
  armadilha da 0046.
- `payables.bank_account_id` / `charges.bank_account_id VARCHAR(36) NULL` — *"de qual conta o
  dinheiro saiu / em qual conta o Pix caiu"*. **Decisão do usuário, AUTORITATIVA.**
- `payables.bank_transaction_id` / `charges.bank_transaction_id VARCHAR(36) NULL` — **cache de
  leitura**. Divergiu do movimento com `origin_id = <lançamento>.id`? Quem manda é o `origin_id`.

**Sem FK dura em nenhuma delas** — padrão do projeto (`charges.client_id`,
`payables.cost_center_id`): a integridade é validada no service, sob RLS. Uma FK entre tabelas com
RLS `FORCE` cria caminhos de erro difíceis de diagnosticar quando a GUC não está setada.

**O índice único parcial é o coração desta migration** (design §3.2):

    CREATE UNIQUE INDEX uq_bank_transactions_origin
        ON bank_transactions (tenant_id, source, origin_id)
        WHERE origin_id IS NOT NULL;

- **É ele — e NÃO o `dedup_hash` — a garantia de idempotência** que o requisito do fundador pede.
  `service._manual_dedup_hash` chaveia no UUID da própria linha, que é único por construção e
  portanto nunca deduplica coisa nenhuma. Preencher a conta duas vezes, reprocessar a mesma baixa,
  um retry de request: quem recusa a segunda linha é **o banco**, fail-closed, no espírito da RLS.
- O `WHERE origin_id IS NOT NULL` é o que o torna utilizável: sem ele, todo movimento de
  `SOURCES_EXTERNA` (que nasce com `origin_id` nulo) colidiria com todo outro movimento externo do
  mesmo `source` — o lançamento manual quebraria no segundo movimento do tenant.
- `tenant_id` é a **PRIMEIRA** coluna pelo mesmo motivo da 0058/0059/0060: índice único é GLOBAL e
  não respeita RLS. Sem ele, o tenant B levaria uma violação de integridade por causa de um dado do
  tenant A — bug **e** vazamento de existência.

`ix_payables_bank_account` em `(tenant_id, bank_account_id)` é só leitura: *"o que saiu desta
conta?"* — a pergunta que a conferência por conta (8.16) e a tela de contas vão fazer.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0061"
down_revision: str | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── bank_transactions: a chave de origem ─────────────────────────────────────────────────
    op.add_column(
        "bank_transactions",
        sa.Column("origin_id", sa.String(64), nullable=True),
    )
    op.create_index(
        "uq_bank_transactions_origin",
        "bank_transactions",
        ["tenant_id", "source", "origin_id"],
        unique=True,
        postgresql_where=sa.text("origin_id IS NOT NULL"),
        sqlite_where=sa.text("origin_id IS NOT NULL"),
    )

    # ── payables: a conta (autoritativa) + o cache do movimento ──────────────────────────────
    op.add_column("payables", sa.Column("bank_account_id", sa.String(36), nullable=True))
    op.add_column("payables", sa.Column("bank_transaction_id", sa.String(36), nullable=True))
    op.create_index(
        "ix_payables_bank_account", "payables", ["tenant_id", "bank_account_id"]
    )

    # ── charges: idem (o recebimento fora do trilho é a 8.15) ────────────────────────────────
    op.add_column("charges", sa.Column("bank_account_id", sa.String(36), nullable=True))
    op.add_column("charges", sa.Column("bank_transaction_id", sa.String(36), nullable=True))


def downgrade() -> None:
    op.drop_column("charges", "bank_transaction_id")
    op.drop_column("charges", "bank_account_id")

    op.drop_index("ix_payables_bank_account", table_name="payables")
    op.drop_column("payables", "bank_transaction_id")
    op.drop_column("payables", "bank_account_id")

    op.drop_index("uq_bank_transactions_origin", table_name="bank_transactions")
    op.drop_column("bank_transactions", "origin_id")
