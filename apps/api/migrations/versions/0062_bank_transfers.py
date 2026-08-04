"""bank_transfers: transferência entre contas próprias (duas pernas, um lançamento) — Story 8.18

Revision ID: 0062
Revises: 0061
Create Date: 2026-08-03

Segundo elo da **Onda 2** do Epic 8 (a origem do movimento bancário). down_revision=**0061**.

  NOTA DE ENCADEAMENTO: o head foi CONFIRMADO programaticamente no momento da implementação
  (`ScriptDirectory.get_heads() == ['0061']`, 2026-08-03), não lido do texto da story (que ainda
  citava **0060**, o head de antes da 8.9) nem do epic — mesma disciplina da `0058`/`0059`/`0060`/
  `0061` e a lição escrita na `0049_investments.py`. **O epic não fixa número; o head real é lei.**
  Encadear num revision antigo cria MÚLTIPLOS heads, `alembic upgrade head` falha com
  "multiple heads" e a suíte `rls_e2e` INTEIRA cai junto — não só esta story. O epic §6.1 manda
  mergear esta story **por último** exatamente para não disputar head com a 8.9 (a 0061).

Estritamente ADITIVA: cria UMA tabela nova (com RLS `FORCE`). NÃO altera nenhuma tabela existente
e **ZERO linhas são lidas ou escritas**: sem `UPDATE`, sem `SELECT`, sem backfill.

  ⚠️ ARMADILHA QUE **NÃO** SE APLICA AQUI — e a declaração é obrigatória, não decorativa:
  a migration roda como o papel dono NÃO-superusuário `e1p_app`, **sem** a GUC
  `app.current_tenant_id`. Sob `FORCE ROW LEVEL SECURITY`, qualquer `UPDATE`/`SELECT` direto numa
  tabela de negócio é filtrado a **ZERO LINHAS, em silêncio** — e o SQLite dos testes unitários não
  pega isso (ver `0046_ledger_classification.py`, que desabilita a RLS na janela do backfill e
  reabilita depois). **Esta migration não faz backfill algum, e por isso o footgun não a atinge.**
  O único backfill do épico está na Onda **2b** (aplicação), de propósito — e é lá, não aqui, que
  a disciplina da 0046 precisa ser reaplicada.

**O que a tabela é** (design `controle-bancario-onda2-design.md` §8; ratificação §C-3):

    bank_transfers = o LANÇAMENTO ("movi R$ 1.000 da conta A para a conta B em 10/07").
    bank_transactions = as duas PERNAS que ele gera (`:out` negativa em A, `:in` positiva em B),
                        pareadas por `transfer_id` (coluna que já existe desde a 0059).

- `amount_cents` é **SEMPRE POSITIVO**; o sinal vive nas pernas. Um valor negativo aqui seria a
  terceira convenção de sinal do repositório. A guarda é do service (padrão do projeto:
  integridade no service, onde ela pode explicar), não um `CheckConstraint`.
- `posted_at` é `DATE`, **jamais `TIMESTAMP`** (design §3.3): extrato bancário brasileiro é por dia,
  e guardar hora só convidaria a conversão UTC↔local que fez eventos sumirem da Agenda
  (`CLAUDE.md` §6.0). Aqui a lição é aplicada na ORIGEM: o tipo não permite o erro.
- `kind` é **GENÉRICO** (`own_transfer | investment_in | investment_out`) e é vocabulário do módulo
  `bank`. **Nada nesta migration, nem no código que a acompanha, conhece `investment_accounts`** —
  a faceta de produto da aplicação (rentabilidade, principal derivado) é Onda 2b. `VARCHAR(20)`
  (não enum no banco) para que crescer o vocabulário não exija migration: a validação mora no
  service, mesmo padrão de `bank_accounts.kind`.
- **Sem FK dura** para `bank_accounts` — padrão do projeto (`charges.client_id`,
  `payables.cost_center_id`): a integridade é validada no service, sob RLS. Uma FK entre tabelas com
  RLS `FORCE` cria caminhos de erro difíceis de diagnosticar quando a GUC não está setada.

**RLS no padrão de `0049_investments.py`**: `ENABLE` + `FORCE` + policy `tenant_isolation` com
`USING` **e** `WITH CHECK`. Sem o `WITH CHECK`, o tenant A conseguiria PLANTAR uma transferência
dentro do tenant B — leitura protegida e escrita aberta é meia proteção.

`ix_bank_transfers_accounts` é só leitura: *"o que passou por esta conta?"* — a pergunta que a tela
de Contas & Saldos faz. `tenant_id` é a primeira coluna dos dois índices pelo mesmo motivo dos
índices únicos deste módulo: índice é global e não respeita RLS.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0062"
down_revision: str | None = "0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enable_rls(table: str) -> None:
    """Cópia literal de `0049_investments.py::_enable_rls`.

    A story manda copiar, não reinventar.
    """
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
        "bank_transfers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        # Referências SOLTAS a `bank_accounts` — sem FK dura (ver a docstring).
        sa.Column("from_account_id", sa.String(36), nullable=False),
        sa.Column("to_account_id", sa.String(36), nullable=False),
        # SEMPRE POSITIVO. Centavos, BigInteger (Regra de Ouro: dinheiro nunca é float).
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        # DATE, nunca TIMESTAMP.
        sa.Column("posted_at", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_bank_transfers_tenant_id", "bank_transfers", ["tenant_id"])
    op.create_index(
        "ix_bank_transfers_accounts",
        "bank_transfers",
        ["tenant_id", "from_account_id", "to_account_id"],
    )
    _enable_rls("bank_transfers")


def downgrade() -> None:
    """Derruba índices e tabela, como a 0049. **Não toca em `bank_transactions`.**

    ⚠️ **DECISÃO DECLARADA — o downgrade NÃO apaga as pernas** (`bank_transactions` com
    `source='transfer'`). Três motivos, nesta ordem:

    1. **Seria backfill sob `FORCE ROW LEVEL SECURITY`.** Um `DELETE FROM bank_transactions WHERE
       source = 'transfer'` rodando como `e1p_app` sem a GUC `app.current_tenant_id` é filtrado a
       **zero linhas, em silêncio** — a armadilha da 0046. O downgrade *pareceria* funcionar e não
       teria apagado nada. Um `DELETE` que mente é pior do que um `DELETE` ausente.
    2. **Apagar linha de `bank_transactions` é decisão de produto, e ela já foi tomada no service**
       (`delete_transfer`, AC8), com a guarda da linha puramente sintética: linha já enriquecida por
       importação **não some**, tem a origem desligada. Uma migration não tem como aplicar essa
       guarda sem reimplementá-la em SQL — duas implementações da mesma regra, e a de SQL sem teste.
    3. **O downgrade é reversível sem perda.** As pernas que sobram continuam sendo movimentos
       legítimos do razão (o dinheiro *saiu* e *entrou* mesmo); o que se perde ao derrubar a tabela
       é o lançamento que as agrupava. Re-aplicar a 0062 devolve a tabela vazia e as pernas órfãs
       permanecem visíveis — estado honesto, não silencioso.

    Consequência para quem operar um downgrade em produção com dado real: **apague as
    transferências pela API (`DELETE /bank/transfers/{id}`) ANTES de derrubar a revision**, e aí as
    duas pernas somem pelo caminho que tem guarda e trilha de auditoria.
    """
    op.drop_index("ix_bank_transfers_accounts", table_name="bank_transfers")
    op.drop_index("ix_bank_transfers_tenant_id", table_name="bank_transfers")
    op.drop_table("bank_transfers")
