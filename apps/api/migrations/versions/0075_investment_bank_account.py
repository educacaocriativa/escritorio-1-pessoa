"""A aplicação aponta para a conta bancária dela (Onda 2b-i)

Revision ID: 0075
Revises: 0074
Create Date: 2026-08-07

**Por quê.** `investments.register_yield` cria uma `Charge` sintética paga (Story 5.6) e nada mais:
o dinheiro que entrou na aplicação real não vira `bank_transaction` nenhum. Isso é o termo **P3** da
pré-condição do gate do Epic 8, e enquanto ele for não-vazio numa janela a divergência daquele ciclo
**não pode ser lida** — nenhuma onda é liberada nem morta com base nele. Esta coluna é o que diz ao
`sync_origin_movement` QUAL conta creditar.

**`investment_accounts` NÃO é absorvida por `bank_accounts`.** Ela é a faceta de PRODUTO
(rentabilidade, indexador, principal); a `bank_account` `kind='investment'` é ONDE o dinheiro está.
São duas coisas, e a ligação é 1:1. Transferir para uma conta de aplicação **já funciona** desde a
Onda 1 — o que faltava era a faceta de produto saber de qual conta ela fala.

⚠️ **NENHUM `UPDATE`, e isso não é economia — é a razão de esta migration ser segura.** As seis
armadilhas registradas neste repo (`0046`, `0066`, `0067`, `0068`, `0069`, `0073`) são todas a
mesma: um `UPDATE` de backfill filtrado em silêncio pela RLS, completando com **sucesso aparente** e
invisível para o SQLite da suíte. `ADD COLUMN` e `CREATE INDEX` são **DDL** — a RLS não os alcança.
A aplicação que já existe em produção é vinculada pelo dono, **por ato**, na tela. **O backfill que
não existe é o backfill que não pode falhar em silêncio.**

⚠️ **`tenant_id` é a PRIMEIRA coluna do índice único, e a ordem não é estética.** Índice único é
global e **não respeita RLS**: sem o `tenant_id` na frente, o tenant B receberia violação de
unicidade causada por dado do tenant A — bug **e** vazamento de existência. Lição já paga na 8.2.

**A cláusula parcial** (`WHERE bank_account_id IS NOT NULL`) mantém N aplicações não-vinculadas
convivendo. Ela **não** é o que garante a distinção dos `NULL` — em índice único `NULL` já é
distinto de `NULL` por padrão, e desde o PG15 isso é inclusive configurável (`NULLS NOT DISTINCT`).
Está aqui por tamanho e por intenção declarada. A justificativa é esta, e não a que o AC da 8.9
escreveu (que era falsa, e cujo mutante sobreviveu por isso).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0075"
down_revision: str | None = "0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "investment_accounts"
_COLUMN = "bank_account_id"
_INDEX = "uq_investment_accounts_bank_account"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(36), nullable=True))
    op.create_index(
        _INDEX,
        _TABLE,
        ["tenant_id", _COLUMN],
        unique=True,
        postgresql_where=sa.text("bank_account_id IS NOT NULL"),
        sqlite_where=sa.text("bank_account_id IS NOT NULL"),
    )


def downgrade() -> None:
    # Não-destrutivo para o que existia antes: `principal_cents` e `accrued_yield_cents` nunca
    # foram tocados. O que se perde é o VÍNCULO — e com ele `register_yield` volta a aceitar
    # rendimento sem perna bancária, reabrindo o termo P3 e fechando o gate do épico de novo.
    # Fica escrito aqui em vez de ser descoberto no meio de um rollback.
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_column(_TABLE, _COLUMN)
