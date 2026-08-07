"""O saldo de abertura passa a registrar o ATO, não só o VALOR (Story 8.21)

Revision ID: 0074
Revises: 0073
Create Date: 2026-08-07

**Por quê.** `bank_accounts.opening_balance_cents` é `NOT NULL DEFAULT 0` e o formulário
pré-preenche `"0,00"` — então *"informei zero"* e *"não informei nada"* são a **mesma linha**. Uma
conta cadastrada por quem não sabia o saldo entra com `0`, vira elegível, e a Projeção de Caixa
passa a afirmar runway e alerta sobre um saldo que **ninguém informou**. `ORIGEM_INDISPONIVEL`
existe em `core/money_planes.py` desde a Onda 0 **sem gatilho**; esta coluna é o gatilho.

**Por que uma coluna irmã e não `opening_balance_cents` anulável** (veredito da @architect):
anulá-la quebraria `bank/service.py::_validate_opening_date_recuo` (Story 8.11), cujo mecanismo
inteiro é *"presença é a única coisa que a API consegue distinguir de 'não mudou'"* — com a coluna
anulável, o `None` de `BankAccountUpdate` passaria a significar **duas** coisas e a guarda contra a
divergência inventada morreria em silêncio. Ela também é a âncora da fórmula do saldo derivado
(design §3.1, `service._balances_for`), e `None` ali se propagaria para `derived_balance` →
`active_balance_total` → Conferência → Contas & Saldos.

⚠️ **NENHUM backfill, e isso não é economia — é a razão de esta migration ser segura.** As seis
armadilhas registradas neste repo (`0046`, `0066`, `0067`, `0068`, `0069`, `0073`) são todas a
mesma: um `UPDATE` de backfill filtrado em silêncio pela RLS, completando com **sucesso aparente**.
`bank_accounts` tem `ENABLE`+`FORCE ROW LEVEL SECURITY` desde a `0058`, mas `ADD COLUMN` é **DDL,
não DML** — a RLS não o alcança, e desde o PG 11 um `server_default` não-volátil vai para o
catálogo (`pg_attribute.attmissingval`) sem reescrever uma linha sequer. **O backfill que não
existe é o backfill que não pode falhar em silêncio.**

⚠️ **`server_default=true` cai logo em seguida, no mesmo `upgrade`.** Ele existe para as linhas
LEGADAS — que continuam afirmando, o que é o comportamento correto hoje e evita suprimir a Projeção
de quem informou o saldo de verdade. Mantido como default permanente, porém, todo `INSERT` que
omitisse a coluna gravaria *"eu sei o saldo"* em silêncio: o defeito desta story reintroduzido pelo
próprio remédio. Derrubado, o esquecimento vira violação de `NOT NULL` na hora. É a mesma disciplina
de `ai.complete` exigir `db`/`tenant_id`/`task` e de `payables.is_overdue` exigir `today`.

⚠️ **`opening_balance_is_known` contém a substring `"balance"`** e por isso trip o gate
`tests/test_bank_accounts.py::test_saldo_derivado_nao_e_coluna_no_modelo`, que existe para impedir
saldo MATERIALIZADO. O gate está certo; a exceção lá é **nominal e justificada** (o ato não é
saldo). **Renomear a coluna para fugir da substring está proibido** — seria deixar o teste ditar o
vocabulário do domínio.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0074"
down_revision: str | None = "0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "bank_accounts"
_COLUMN = "opening_balance_is_known"


def upgrade() -> None:
    # 1) A coluna nasce com default `true`: é ele que "backfilla" as linhas legadas, no catálogo,
    #    sem UPDATE e portanto sem exposição à armadilha da RLS.
    op.add_column(
        _TABLE,
        sa.Column(_COLUMN, sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    # 2) E some no mesmo passo. A partir daqui, quem insere DECLARA — ver a nota no topo.
    op.alter_column(_TABLE, _COLUMN, server_default=None)


def downgrade() -> None:
    # Reversível e não-destrutivo para o que existia antes: `opening_balance_cents` nunca foi
    # tocado. O que se perde é o FATO NOVO — quem havia declarado "não sei o saldo" volta a ser
    # indistinguível de quem declarou zero, e a Projeção volta a afirmar sobre essas contas.
    # Fica escrito aqui em vez de ser descoberto no meio de um rollback.
    op.drop_column(_TABLE, _COLUMN)
