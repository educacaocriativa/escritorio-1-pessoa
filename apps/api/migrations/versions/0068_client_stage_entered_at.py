"""Ordem de entrada na etapa: clients.stage_entered_at

Revision ID: 0068
Revises: 0067
Create Date: 2026-08-05

O board do Kanban ordenava por `Client.name`. Como a maioria dos leads entra pelo WhatsApp sem
nome resolvido, o "nome" é o telefone e a coluna Entrada aparecia em ordem numérica de DDI. O
dono precisa atender por ordem de chegada, e "quando este card entrou nesta etapa" não estava
gravado em lugar nenhum.

⚠️ ARMADILHA QUE **SE APLICA** AQUI: esta migration FAZ BACKFILL de `clients`. Ela roda como o
papel dono NÃO-superusuário `e1p_app`, **sem** a GUC `app.current_tenant_id`. Sob `FORCE ROW
LEVEL SECURITY`, o `UPDATE` seria filtrado a **ZERO LINHAS, em silêncio** — e o sintoma em
produção não seria um erro de deploy, seria "a fila continua fora de ordem". Por isso a RLS de
`clients` é desabilitada SÓ na janela do backfill e restaurada (ENABLE + FORCE) logo depois —
mesmo padrão da `0046`, `0066` e `0067`. DDL é transacional no Postgres e a migration roda
offline, então não há janela de exposição.

A coluna é `NOT NULL` no destino mas **não pode nascer assim**: nascer com
`server_default=now()` carimbaria todo card existente com o instante do deploy, e o backfill
teria de desfazer isso. Ordem: nullable → backfill → NOT NULL + server_default.

O backfill usa o melhor sinal disponível por linha: o último `stage_move`/`reopened` daquele
contato, e `clients.created_at` quando não houver evento (card anterior à 0067, ou card que
nunca se moveu — que é o caso da maioria). Errado no detalhe para card movido antes da 0067,
mas monotônico e sem buraco.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0068"
down_revision: str | None = "0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "clients", sa.Column("stage_entered_at", sa.DateTime(timezone=True), nullable=True)
    )

    # --- backfill (ver a ARMADILHA no docstring: sem esta janela, tudo abaixo é no-op) ---
    op.execute("ALTER TABLE clients DISABLE ROW LEVEL SECURITY")

    op.execute(
        """
        UPDATE clients SET stage_entered_at = COALESCE(
            (SELECT MAX(e.created_at) FROM client_events e
              WHERE e.client_id = clients.id AND e.kind IN ('stage_move', 'reopened')),
            clients.created_at
        )
        """
    )

    op.execute("ALTER TABLE clients ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE clients FORCE ROW LEVEL SECURITY")

    op.alter_column(
        "clients",
        "stage_entered_at",
        nullable=False,
        server_default=sa.text("now()"),
    )


def downgrade() -> None:
    op.drop_column("clients", "stage_entered_at")
