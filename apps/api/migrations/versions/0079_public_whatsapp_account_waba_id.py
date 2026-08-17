"""Roteamento do webhook por WABA: public_whatsapp_accounts.waba_id

Revision ID: 0079
Revises: 0078
Create Date: 2026-08-17

O webhook público da Meta resolve o tenant pelo `phone_number_id` que vem em
`value.metadata` — é o que o evento de MENSAGEM carrega. O evento de aprovação de template
(`message_template_status_update`) NÃO carrega telefone nenhum: ele identifica a conta pelo
WABA ID, em `entry[].id`. Sem esta coluna, o evento chega e morre em 404.

Nullable de propósito: as linhas já existentes precedem a coluna, e `NOT NULL` sem default
derrubaria o deploy. O dual-write de `settings/service.py::_sync_whatsapp_webhook_snapshot`
sempre preenche daqui pra frente (o snapshot só é criado quando as 4 credenciais existem, e
`whatsapp_waba_id` é uma delas), e o backfill abaixo cobre quem já estava configurado.

⚠️ ARMADILHA QUE **SE APLICA** AQUI: esta migration FAZ BACKFILL lendo `tenant_profiles`, que
tem `FORCE ROW LEVEL SECURITY` desde a 0022. Ela roda como o papel dono não-superusuário
`e1p_app`, **sem** a GUC `app.current_tenant_id` — a RLS filtra SELECT também, então o
`UPDATE ... FROM tenant_profiles` seria filtrado a **ZERO LINHAS, EM SILÊNCIO**. Em produção o
sintoma não seria erro de deploy: seria todo tenant já configurado continuar sem receber o
evento de aprovação, e ninguém descobre até alguém reclamar que o template "ficou pendente
pra sempre". Por isso a RLS é desabilitada em `tenant_profiles` (a FONTE) na janela do
backfill e restaurada com ENABLE + FORCE logo depois. Mesmo padrão da 0046, 0066, 0067, 0068
e 0078.

O ALVO (`public_whatsapp_accounts`) NÃO precisa de janela: é tabela GLOBAL, criada na 0054 sem
`ENABLE ROW LEVEL SECURITY` — é justamente por não ter RLS que ela serve pra resolver tenant
antes de qualquer autenticação.

DDL é transacional no Postgres e a migration roda offline, então não há janela de exposição.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0079"
down_revision: str | None = "0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def backfill_waba_id() -> None:
    """A janela de RLS na FONTE + o UPDATE reentrante (ver ARMADILHA no docstring do módulo).

    Extraído como função própria (em vez de inline em `upgrade()`) seguindo o precedente da
    0078: o teste de RLS reexecuta exatamente este código — o mesmo que rodaria numa
    reexecução manual contra produção — sem duplicar a SQL numa cópia que poderia divergir.
    """
    op.execute("ALTER TABLE tenant_profiles DISABLE ROW LEVEL SECURITY")

    op.execute(
        """
        UPDATE public_whatsapp_accounts AS a
           SET waba_id = p.whatsapp_waba_id
          FROM tenant_profiles AS p
         WHERE p.tenant_id = a.tenant_id
           AND p.whatsapp_waba_id IS NOT NULL
           AND a.waba_id IS NULL
        """
    )

    op.execute("ALTER TABLE tenant_profiles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_profiles FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    op.add_column(
        "public_whatsapp_accounts", sa.Column("waba_id", sa.String(64), nullable=True)
    )
    op.create_index(
        "ix_public_whatsapp_accounts_waba_id", "public_whatsapp_accounts", ["waba_id"]
    )

    # --- backfill (ver a ARMADILHA no docstring: sem esta janela, tudo aqui é no-op) ---
    backfill_waba_id()


def downgrade() -> None:
    op.drop_index(
        "ix_public_whatsapp_accounts_waba_id", table_name="public_whatsapp_accounts"
    )
    op.drop_column("public_whatsapp_accounts", "waba_id")
