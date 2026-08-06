"""Registro de Fatos: cria `facts` e absorve `client_events`

Revision ID: 0069
Revises: 0068
Create Date: 2026-08-06

`client_events` era a linha do tempo narrativa do CRM. `facts` é a mesma ideia para o negócio
inteiro, com duas colunas que o antecessor não tinha: `module` (o eixo de permissão do
briefing, vocabulário de `User.allowed_modules`) e `occurred_at` (quando aconteceu, distinto
de quando gravamos).

Consolidar em vez de coexistir: `client_events` nasceu em 2026-08-04 com pouquíssimos registros
(dois tenants em teste). É o momento mais barato que vai existir para unificar.

⚠️ ARMADILHA QUE **SE APLICA** AQUI: o INSERT ... SELECT abaixo lê `client_events` e escreve em
`facts`. A migration roda como o papel dono NÃO-superusuário `e1p_app`, **sem** a GUC
`app.current_tenant_id`. Sob `FORCE ROW LEVEL SECURITY`, o SELECT devolve zero linhas e o
INSERT grava zero — **em silêncio**. O sintoma em produção não seria erro de deploy, seria "a
linha do tempo de todo contato está vazia", já com a origem dropada. Por isso a RLS das DUAS
tabelas é desabilitada só na janela e restaurada logo depois — mesmo padrão da 0046, 0066,
0067 e 0068. DDL é transacional no Postgres e a migration roda offline, então não há janela de
exposição.

`occurred_at` herda `client_events.created_at`: é o melhor sinal disponível para um registro
que nunca soube distinguir "aconteceu" de "foi gravado".

Um `kind` fora do de-para vira `crm.evento.<kind>` em vez de NULL — um valor novo vindo de um
backend mais recente cai num rótulo honesto em vez de sumir (mesmo princípio de
`_titulo_de_chegada` no CRM).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0069"
down_revision: str | None = "0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `client_events.kind` era curto e implicitamente do CRM. A taxonomia nova é explícita.
_DE_PARA_KIND = {
    "lead_created": "crm.lead.criado",
    "lead_return": "crm.lead.retornou",
    "stage_move": "crm.etapa.movida",
    "reopened": "crm.lead.reaberto",
    "note": "crm.nota.criada",
    "funnel": "crm.funil.inscrito",
}


def upgrade() -> None:
    op.create_table(
        "facts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("module", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=48), nullable=False),
        sa.Column("title", sa.String(length=140), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("client_id", sa.String(length=36), nullable=True),
        sa.Column("subject_type", sa.String(length=32), nullable=True),
        sa.Column("subject_id", sa.String(length=36), nullable=True),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("is_ai", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False, server_default="emitted"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"], name="fk_facts_client", ondelete="CASCADE"
        ),
    )
    # A janela do briefing: "o que aconteceu neste tenant desde X".
    op.create_index("ix_facts_tenant_occurred", "facts", ["tenant_id", "occurred_at"])
    # A timeline do contato: "os N mais recentes desta pessoa".
    op.create_index("ix_facts_client_occurred", "facts", ["client_id", "occurred_at"])
    # O filtro de permissão do briefing.
    op.create_index(
        "ix_facts_tenant_module_occurred", "facts", ["tenant_id", "module", "occurred_at"]
    )

    op.execute("ALTER TABLE facts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE facts FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON facts
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )

    # --- migração dos dados (ver a ARMADILHA no docstring) ---
    # AS DUAS tabelas: `client_events` porque é a FONTE do SELECT, `facts` porque é o ALVO do
    # INSERT. A RLS filtra SELECT também — com ela ligada na origem, o INSERT roda, não falha,
    # e grava zero linhas.
    op.execute("ALTER TABLE client_events DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE facts DISABLE ROW LEVEL SECURITY")

    caso = " ".join(f"WHEN '{antigo}' THEN '{novo}'" for antigo, novo in _DE_PARA_KIND.items())
    op.execute(
        f"""
        INSERT INTO facts (
            id, tenant_id, module, kind, title, body, client_id,
            subject_type, subject_id, actor, is_ai, occurred_at, origin,
            created_at, updated_at
        )
        SELECT
            e.id, e.tenant_id, 'crm',
            CASE e.kind {caso} ELSE 'crm.evento.' || e.kind END,
            e.title, e.body, e.client_id,
            'client', e.client_id, e.actor, e.is_ai, e.created_at, 'emitted',
            e.created_at, e.updated_at
        FROM client_events e
        """
    )

    op.execute("ALTER TABLE facts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE facts FORCE ROW LEVEL SECURITY")

    op.drop_table("client_events")


def downgrade() -> None:
    """Recria `client_events` vazia. Os dados NÃO voltam.

    Reverter é destrutivo de propósito: fatos de outros módulos gravados depois da 0069 não
    têm para onde ir em `client_events`, que só conhece contatos. Restaurar dados exige backup.
    """
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
            ["client_id"], ["clients.id"], name="fk_client_events_client", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_client_events_client_id", "client_events", ["client_id"])
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
    op.drop_table("facts")
