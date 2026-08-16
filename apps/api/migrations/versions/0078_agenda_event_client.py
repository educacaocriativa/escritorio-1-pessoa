"""Vínculo do compromisso com o contato: agenda_events.client_id

Revision ID: 0078
Revises: 0077
Create Date: 2026-08-16

A Agenda não sabia de que contato era um compromisso. O nome que a tela mostrava era
DERIVADO da cobrança, por um caminho polimórfico via `external_ref` — que já está ocupado
apontando para cobrança e para conta a pagar, conforme o `kind`.

SEM FK, `String(36)`, seguindo o precedente de `whatsapp_chats.client_id`: a Agenda não deve
ganhar dependência dura da tabela do CRM. Nullable é o caso NORMAL — bloqueio de horário,
prazo interno e conta a pagar não têm cliente.

⚠️ ARMADILHA QUE **SE APLICA** AQUI: esta migration FAZ BACKFILL. Ela roda como o papel dono
não-superusuário `e1p_app`, **sem** a GUC `app.current_tenant_id`. Sob `FORCE ROW LEVEL
SECURITY` o `UPDATE` seria filtrado a **ZERO LINHAS, EM SILÊNCIO** — e o sintoma em produção
não seria erro de deploy, seria "a ficha não mostra compromisso nenhum". Por isso a RLS é
desabilitada nas DUAS tabelas na janela do backfill (`agenda_events` porque é o ALVO,
`charges` porque é a FONTE da subconsulta — a RLS filtra SELECT também) e restaurada com
ENABLE + FORCE logo depois. Mesmo padrão da 0046, 0066, 0067 e 0068. DDL é transacional no
Postgres e a migration roda offline, então não há janela de exposição.

O backfill filtra por `kind='cobranca_receber'`. Sem esse filtro, um evento de conta a pagar
cujo `external_ref` colidisse com o id de uma cobrança ganharia um dono errado — `external_ref`
é ponteiro polimórfico, e o `kind` é o discriminador.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0078"
down_revision: str | None = "0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agenda_events", sa.Column("client_id", sa.String(36), nullable=True))
    op.create_index(
        "ix_agenda_events_client_id", "agenda_events", ["client_id"]
    )

    # --- backfill (ver a ARMADILHA no docstring: sem esta janela, tudo abaixo é no-op) ---
    op.execute("ALTER TABLE agenda_events DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE charges DISABLE ROW LEVEL SECURITY")

    op.execute(
        """
        UPDATE agenda_events AS e
           SET client_id = c.client_id
          FROM charges AS c
         WHERE e.external_ref = c.id
           AND e.kind = 'cobranca_receber'
           AND c.client_id IS NOT NULL
           AND e.tenant_id = c.tenant_id
        """
    )

    op.execute("ALTER TABLE agenda_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agenda_events FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE charges ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE charges FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_agenda_events_client_id", table_name="agenda_events")
    op.drop_column("agenda_events", "client_id")
