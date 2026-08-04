"""Linha do tempo do contato + chave de deduplicação de telefone

Revision ID: 0067
Revises: 0066
Create Date: 2026-08-04

O mesmo contato virava vários cards no Kanban: `pages/service.py::public_submit` e
`integrations/service.py::capture_lead` chamavam `create_client` incondicionalmente, sem
procurar se aquela pessoa já existia. Esta migration cria as duas estruturas que faltavam:

- **`client_events`** — a linha do tempo NARRATIVA do contato (como chegou, quando voltou,
  para onde foi no Kanban, o que foi decidido). Dinheiro NÃO entra aqui: orçamento, cobrança
  e pagamento continuam sendo lidos de `quotes`/`charges`.
- **`clients.phone_key`** — a forma comparável do telefone (`"5511999998888"`), ao lado do
  `phone` cru, que continua guardando o que a pessoa digitou.

⚠️ ARMADILHA QUE **SE APLICA** AQUI: esta migration FAZ BACKFILL de `clients.phone_key`. Ela
roda como o papel dono NÃO-superusuário `e1p_app`, **sem** a GUC `app.current_tenant_id`. Sob
`FORCE ROW LEVEL SECURITY`, o `UPDATE` seria filtrado a **ZERO LINHAS, em silêncio** — e o
sintoma em produção não seria um erro, seria "continua duplicando contato". Por isso a RLS de
`clients` é desabilitada SÓ na janela do backfill e restaurada (ENABLE + FORCE) logo depois —
mesmo padrão da `0046_ledger_classification` e da `0066_whatsapp_chats`. DDL é transacional no
Postgres e a migration roda offline, então não há janela de exposição.

**A normalização está DUPLICADA de propósito.** `_normalize_br_frozen` abaixo é uma cópia
congelada de `app.core.phone.normalize_br` nesta revisão. Nenhuma migration do repo importa de
`app.` — migration é registro histórico, e importar código vivo faria "rodar as migrations do
zero" produzir um resultado diferente do que a produção recebeu se a regra mudasse depois. O
teste `tests/test_migration_0067_phone_key.py` prova que as duas concordam hoje.

**O backfill é aditivo e não-destrutivo:** preenche uma coluna nova, não altera `phone` e não
mescla card nenhum. Os cards duplicados que já existem CONTINUAM duplicados (decisão do
fundador: a correção vale daqui para frente) — eles passam a compartilhar `phone_key`, e o
desempate de qual deles recebe um retorno futuro é o "mais antigo primeiro" de
`crm/service.py::absorb_lead`.
"""
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0067"
down_revision: str | None = "0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NON_DIGITS = re.compile(r"\D")
_MOBILE_FIRST_DIGITS = "6789"


def _normalize_br_frozen(raw: str | None) -> str | None:
    """Cópia CONGELADA de `app.core.phone.normalize_br` na revisão 0067.

    Não editar para "acompanhar" mudanças futuras da regra: o backfill que a produção
    recebeu foi este. Uma regra nova pede uma migration nova.
    """
    digits = _NON_DIGITS.sub("", raw or "")
    if not digits:
        return None
    if digits.startswith("55") and len(digits) - 2 in (10, 11):
        digits = digits[2:]
    if len(digits) not in (10, 11):
        return None
    ddd, local = digits[:2], digits[2:]
    if ddd[0] == "0":
        return None
    if len(local) == 8 and local[0] in _MOBILE_FIRST_DIGITS:
        local = "9" + local
    return "55" + ddd + local


def upgrade() -> None:
    op.create_table(
        "client_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("client_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=140), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("is_ai", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"],
            name="fk_client_events_client", ondelete="CASCADE",
        ),
    )
    op.create_index("ix_client_events_client_id", "client_events", ["client_id"])
    # A timeline sempre lê "os N mais recentes deste contato" — o índice composto serve
    # exatamente essa consulta.
    op.create_index(
        "ix_client_events_client_created", "client_events", ["client_id", "created_at"]
    )

    op.execute("ALTER TABLE client_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE client_events FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON client_events
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )

    op.add_column("clients", sa.Column("phone_key", sa.String(length=16), nullable=True))
    op.create_index("ix_clients_phone_key", "clients", ["phone_key"])

    # --- backfill (ver a ARMADILHA no docstring: sem esta janela, tudo abaixo é no-op) ---
    op.execute("ALTER TABLE clients DISABLE ROW LEVEL SECURITY")

    bind = op.get_bind()
    linhas = bind.execute(
        sa.text("SELECT id, phone FROM clients WHERE phone IS NOT NULL AND phone <> ''")
    ).fetchall()
    for linha in linhas:
        chave = _normalize_br_frozen(linha.phone)
        if chave is None:
            continue  # telefone que não normaliza fica sem chave; não se adivinha
        bind.execute(
            sa.text("UPDATE clients SET phone_key = :chave WHERE id = :id"),
            {"chave": chave, "id": linha.id},
        )

    op.execute("ALTER TABLE clients ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE clients FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_clients_phone_key", table_name="clients")
    op.drop_column("clients", "phone_key")
    op.drop_index("ix_client_events_client_created", table_name="client_events")
    op.drop_index("ix_client_events_client_id", table_name="client_events")
    op.drop_table("client_events")
